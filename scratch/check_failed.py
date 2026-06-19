from redis import Redis
from rq import Queue
from rq.registry import FailedJobRegistry
r = Redis('redis', 6379, db=0)
q = Queue(connection=r)
failed = FailedJobRegistry(queue=q)
for job_id in failed.get_job_ids():
    job = q.fetch_job(job_id)
    print(f"Job {job_id} exception:")
    print(job.exc_info)
