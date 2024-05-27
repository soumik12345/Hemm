import base64
import io
from PIL import Image
from pathlib import Path
from typing import Callable, Dict, List, Optional, Union

import weave
from datasets import load_dataset
from tqdm.auto import tqdm
from weave.trace.refs import ObjectRef


EXT_TO_MIMETYPE = {
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".svg": "image/svg+xml",
}


def base64_encode_image(
    image_path: Union[str, Image.Image], mimetype: Optional[str] = None
) -> str:
    image = Image.open(image_path) if isinstance(image_path, str) else image_path
    mimetype = (
        EXT_TO_MIMETYPE[Path(image_path).suffix]
        if isinstance(image_path, str)
        else "image/png"
    )
    byte_arr = io.BytesIO()
    image.save(byte_arr, format="PNG")
    encoded_string = base64.b64encode(byte_arr.getvalue()).decode("utf-8")
    encoded_string = f"data:{mimetype};base64,{encoded_string}"
    return str(encoded_string)


def publish_dataset_to_weave(
    dataset_path,
    dataset_name: Optional[str] = None,
    prompt_column: Optional[str] = None,
    ground_truth_image_column: Optional[str] = None,
    split: Optional[str] = None,
    data_limit: Optional[int] = None,
    get_weave_dataset_reference: bool = True,
    dataset_transforms: Optional[List[Callable]] = None,
    column_transforms: Optional[Dict[str, Callable]] = None,
    *args,
    **kwargs,
) -> Union[ObjectRef, None]:
    dataset_name = dataset_name or Path(dataset_path).stem
    dataset_dict = load_dataset(dataset_path, *args, **kwargs)
    dataset_dict = dataset_dict[split] if split else dataset_dict["train"]
    dataset_dict = (
        dataset_dict.take(data_limit)
        if data_limit is not None and data_limit < len(dataset_dict)
        else dataset_dict
    )
    if dataset_transforms:
        for transform in dataset_transforms:
            dataset_dict = dataset_dict.map(transform)
    dataset_dict = (
        dataset_dict.rename_column(prompt_column, "prompt")
        if prompt_column
        else dataset_dict
    )
    dataset_dict = (
        dataset_dict.rename_column(ground_truth_image_column, "ground_truth_image")
        if ground_truth_image_column
        else dataset_dict
    )
    column_transforms = (
        {**column_transforms, **{"ground_truth_image": base64_encode_image}}
        if column_transforms
        else {"ground_truth_image": base64_encode_image}
    )
    weave_dataset_rows = []
    for data_item in tqdm(dataset_dict):
        for key in data_item.keys():
            if column_transforms and key in column_transforms:
                data_item[key] = column_transforms[key](data_item[key])
        weave_dataset_rows.append(data_item)
    weave_dataset = weave.Dataset(name=dataset_name, rows=weave_dataset_rows)
    weave.publish(weave_dataset)
    return weave.ref(dataset_name).get() if get_weave_dataset_reference else None
