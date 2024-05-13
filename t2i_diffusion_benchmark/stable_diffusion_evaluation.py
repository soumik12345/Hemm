import asyncio
import os
from functools import partial
from typing import Dict

import numpy as np

import torch
from torchmetrics.functional.multimodal import clip_score
from diffusers import StableDiffusionPipeline
from diffusers.utils.loading_utils import load_image

import wandb
import weave
from weave import Evaluation


class StableDiffusionEvaluationPipeline:

    def __init__(
        self,
        diffusion_model_name_or_path: str,
        clip_model_name_or_path: str = "openai/clip-vit-base-patch16",
        torch_dtype: torch.dtype = torch.float16,
        enable_cpu_offfload: bool = False,
        seed: int = 42,
    ) -> None:
        self.diffusion_model_name_or_path = diffusion_model_name_or_path
        self.clip_model_name_or_path = clip_model_name_or_path
        self.torch_dtype = torch_dtype
        self.enable_cpu_offfload = enable_cpu_offfload
        self.seed = seed

        self.generated_images_dir = os.path.join(os.getcwd(), "generated_images")
        os.makedirs(self.generated_images_dir, exist_ok=True)

        self.pipeline = StableDiffusionPipeline.from_pretrained(
            diffusion_model_name_or_path, torch_dtype=torch_dtype
        )

        if enable_cpu_offfload:
            self.pipeline.enable_model_cpu_offload()
        else:
            self.pipeline = self.pipeline.to("cuda")
        self.pipeline.set_progress_bar_config(leave=False, desc="Generating Image")

        self.clip_score_fn = partial(
            clip_score, model_name_or_path=clip_model_name_or_path
        )

        self.inference_counter = 1
        self.wandb_table = wandb.Table(
            columns=["model", "prompt", "image", "clip_score"]
        )

        self.evaluation_configs = {
            "diffusion_pipeline": dict(self.pipeline.config),
            "clip_model_name_or_path": clip_model_name_or_path,
            "torch_dtype": str(torch_dtype),
            "enable_cpu_offfload": enable_cpu_offfload,
            "seed": seed,
        }

        self.metric_functions = [self.calculate_clip_score]

    @weave.op()
    async def infer(self, prompt: str) -> Dict[str, str]:
        image_url = os.path.join(
            self.generated_images_dir, f"{self.inference_counter}.png"
        )
        self.inference_counter += 1
        self.pipeline(
            prompt,
            num_images_per_prompt=1,
            generator=torch.Generator(device="cuda").manual_seed(self.seed),
        ).images[0].save(image_url)
        return {"image_url": image_url}

    @weave.op()
    async def calculate_clip_score(
        self, prompt: str, model_output: Dict
    ) -> Dict[str, float]:
        pil_image = load_image(model_output["image_url"])
        images = np.expand_dims(np.array(pil_image), axis=0)
        clip_score = float(
            self.clip_score_fn(
                torch.from_numpy(images).permute(0, 3, 1, 2), prompt
            ).detach()
        )
        self.wandb_table.add_data(
            self.diffusion_model_name_or_path,
            prompt,
            wandb.Image(pil_image),
            clip_score,
        )
        return {"clip_score": clip_score}

    def log_summary(self, init_params: Dict):
        if wandb.run is None:
            wandb.init(**init_params)
        config = wandb.config
        config.update(self.evaluation_configs)
        wandb.log({"Evalution": self.wandb_table})

    def __call__(self, dataset: Dict, init_params: Dict):
        weave.init(project_name="t2i_eval")
        evaluation = Evaluation(dataset=dataset, scorers=[self.calculate_clip_score])
        with weave.attributes(self.evaluation_configs):
            asyncio.run(evaluation.evaluate(self.infer))
        self.log_summary(init_params)