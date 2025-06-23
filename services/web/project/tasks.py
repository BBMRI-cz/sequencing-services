from .redis_client import redis_client
from .utils import threaded_copy
from .celery_app import celery
from typing import Dict, List, Any


@celery.task
def copy_multiple_runs_task(runs_data: Dict[str, Dict[str, Any]], job_id: str):
    for only_run, data in runs_data.items():
        run_path = data["run_path"]
        samples_pseudo = data["samples_pseudo"]
        samples_pred = data["samples_pred"]

        dest = f"/RETRIEVED/{only_run}"
        threaded_copy(run_path, dest, samples_pseudo, samples_pred, True, job_id)

    msg = f"Job {job_id} finished"
    redis_client.publish(job_id, msg)


@celery.task
def copy_multiple_samples_task(samples: List[Dict[str, Any]], job_id: str):
    for i, sample in enumerate(samples, start=1):
        src = sample["path"]
        dest = f"/RETRIEVED/{sample['pseudonym']}"
        pseudonym = sample["pseudonym"]
        pred_num = sample["pred_number"]

        threaded_copy(src, dest, pseudonym, pred_num, False, job_id)

    msg = f"Job {job_id} finished"
    redis_client.publish(job_id, msg)
