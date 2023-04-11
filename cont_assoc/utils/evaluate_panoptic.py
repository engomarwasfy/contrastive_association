import yaml
import numpy as np
import time
from cont_assoc.utils.eval_np import PanopticEval



class PanopticKittiEvaluator:
    def __init__(self, cfg):

        dataset_config_file = cfg.DATA_CONFIG.CONFIG_FILE
        self.load_kitti_config(dataset_config_file)
        min_points = 50
        self.evaluator = PanopticEval(self.nr_classes, None, self.ignore_class,
                                      min_points=min_points)
        self.class_metrics = {}
        self.mean_metrics = {}

    def load_kitti_config(self, config_file):
        #Load semantic-kitti config
        # data = yaml.safe_load(open('datasets/semantic-kitti.yaml', 'r'))
        data = yaml.safe_load(open(config_file, 'r'))
        # get number of interest classes, and the label mappings
        class_remap = data["learning_map"]
        self.class_inv_remap = data["learning_map_inv"]
        class_ignore = data["learning_ignore"]
        self.nr_classes = len(self.class_inv_remap)
        self.class_strings = data["labels"]
        # make lookup table for mapping
        maxkey = max(class_remap.keys())
        # +100 hack making lut bigger just in case there are unknown labels
        class_lut = np.zeros((maxkey + 100), dtype=np.int32)
        class_lut[list(class_remap.keys())] = list(class_remap.values())
        self.ignore_class = [cl for cl, ignored in class_ignore.items() if ignored]

        self.class_inv_lut = np.zeros((20), dtype=np.int32)
        self.class_inv_lut[list(self.class_inv_remap.keys())] = list(self.class_inv_remap.values())

        self.things = ['car', 'truck', 'bicycle', 'motorcycle', 'other-vehicle', 'person', 'bicyclist', 'motorcyclist']
        self.stuff = [
            'road', 'sidewalk', 'parking', 'other-ground', 'building', 'vegetation', 'trunk', 'terrain', 'fence', 'pole',
            'traffic-sign'
        ]
        self.all_classes = self.things + self.stuff

    def update(self, sem_preds, ins_preds, inputs):
        for i in range(len(sem_preds)):
            self.evaluator.addBatch_w_fname(sem_preds[i], ins_preds[i],
                                            inputs['pt_labs'][i].reshape(-1),
                                            inputs['pt_ins_labels'][i].reshape(-1),
                                            inputs['pcd_fname'][i])
        self.update_metrics()
    def get_class_inv_lut(self):
        return self.class_inv_lut

    def update_metrics(self):
        class_PQ, class_SQ, class_RQ, class_all_PQ, class_all_SQ, class_all_RQ = self.evaluator.getPQ()
        class_IoU, class_all_IoU = self.evaluator.getSemIoU()

        # make python variables
        class_PQ = class_PQ.item()
        class_SQ = class_SQ.item()
        class_RQ = class_RQ.item()
        class_all_PQ = class_all_PQ.flatten().tolist()
        class_all_SQ = class_all_SQ.flatten().tolist()
        class_all_RQ = class_all_RQ.flatten().tolist()
        class_IoU = class_IoU.item()
        class_all_IoU = class_all_IoU.flatten().tolist()

        output_dict = {
            "all": {
                "PQ": class_PQ,
                "SQ": class_SQ,
                "RQ": class_RQ,
                "IoU": class_IoU,
            }
        }

        classwise_tables = {}

        for idx, (pq, rq, sq, iou) in enumerate(zip(class_all_PQ, class_all_RQ, class_all_SQ, class_all_IoU)):
            class_str = self.class_strings[self.class_inv_remap[idx]]
            output_dict[class_str] = {"PQ": pq, "SQ": sq, "RQ": rq, "IoU": iou}
        #Save per class metrics
        self.class_metrics = output_dict

        PQ_all = np.mean([float(output_dict[c]["PQ"]) for c in self.all_classes])
        PQ_dagger = np.mean([float(output_dict[c]["PQ"]) for c in self.things] + [float(output_dict[c]["IoU"]) for c in self.stuff])
        RQ_all = np.mean([float(output_dict[c]["RQ"]) for c in self.all_classes])
        SQ_all = np.mean([float(output_dict[c]["SQ"]) for c in self.all_classes])

        PQ_things = np.mean([float(output_dict[c]["PQ"]) for c in self.things])
        RQ_things = np.mean([float(output_dict[c]["RQ"]) for c in self.things])
        SQ_things = np.mean([float(output_dict[c]["SQ"]) for c in self.things])

        PQ_stuff = np.mean([float(output_dict[c]["PQ"]) for c in self.stuff])
        RQ_stuff = np.mean([float(output_dict[c]["RQ"]) for c in self.stuff])
        SQ_stuff = np.mean([float(output_dict[c]["SQ"]) for c in self.stuff])
        mIoU = output_dict["all"]["IoU"]

        codalab_output = {
            "pq_mean": float(PQ_all),
            "pq_dagger": float(PQ_dagger),
            "sq_mean": float(SQ_all),
            "rq_mean": float(RQ_all),
            "iou_mean": float(mIoU),
            "pq_stuff": float(PQ_stuff),
            "rq_stuff": float(RQ_stuff),
            "sq_stuff": float(SQ_stuff),
            "pq_things": float(PQ_things),
            "rq_things": float(RQ_things),
            "sq_things": float(SQ_things),
        }

        #Save mean metrics
        self.mean_metrics = codalab_output

    def get_mean_pq(self):
        return self.mean_metrics['pq_mean']

    def get_class_metrics(self):
        return self.class_metrics

    def print_results(self):
        evaluated_fnames = self.evaluator.evaluated_fnames
        print(
            f'Evaluated {len(evaluated_fnames)} frames. Duplicated frame number: {len(evaluated_fnames) - len(set(evaluated_fnames))}'
        )

        print('|        |   PQ   |   RQ   |   SQ   |  IoU   |')
        for k, v in self.class_metrics.items():
            print('|{}| {:.4f} | {:.4f} | {:.4f} | {:.4f} |'.format(
                k.ljust(8)[-8:], v['PQ'], v['RQ'], v['SQ'], v['IoU']
            ))
        for key in self.mean_metrics.keys():
            print("{}:\t{}".format(key, self.mean_metrics[key]))

    def print_fp_fn(self):
        print('True Positive: ')
        print('\t|\t'.join([str(x) for x in self.evaluator.pan_tp]))
        print('False Positive: ')
        print('\t|\t'.join([str(x) for x in self.evaluator.pan_fp]))
        print('False Negative: ')
        print('\t|\t'.join([str(x) for x in self.evaluator.pan_fn]))

