import base64
from io import BytesIO
from typing import List

import torch
from transformers import DetrImageProcessor, DetrForObjectDetection

import weave

from .commons import BoundingBox, CartesianCoordinate2D


class DETRSpatialRelationShipJudge(weave.Model):
    model_address: str = "facebook/detr-resnet-50"
    revision: str = "no_timm"

    def _initialize_models(self):
        self.feature_extractor = DetrImageProcessor.from_pretrained(
            self.model_address, revision=self.revision
        )
        self.object_detection_model = DetrForObjectDetection.from_pretrained(
            self.model_address, revision=self.revision
        )

    @weave.op()
    def predict(self, image: str) -> List[BoundingBox]:
        pil_image = BytesIO(base64.b64decode(image.split(";base64,")[-1]))
        encoding = self.feature_extractor(pil_image, return_tensors="pt")
        outputs = self.object_detection_model(**encoding)
        target_sizes = torch.tensor([image.size[::-1]])
        results = self.feature_extractor.post_process_object_detection(
            outputs, target_sizes=target_sizes, threshold=0.9
        )[0]
        bboxes = []
        for score, label, box in zip(
            results["scores"], results["labels"], results["boxes"]
        ):
            xmin, ymin, xmax, ymax = box.tolist()
            bboxes.append(
                BoundingBox(
                    box_coordinates_min=CartesianCoordinate2D(x=xmin, y=ymin),
                    box_coordinates_max=CartesianCoordinate2D(x=xmax, y=ymax),
                    box_coordinates_center=CartesianCoordinate2D(
                        x=(xmin + xmax) / 2, y=(ymin + ymax) / 2
                    ),
                    label=self.object_detection_model.config.id2label[label.item()],
                    score=score.item(),
                )
            )
        return bboxes