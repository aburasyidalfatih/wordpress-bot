from redis import Redis
from rq import Queue
from rq.registry import StartedJobRegistry, FailedJobRegistry, FinishedJobRegistry
r = Redis('redis', 6379, db=0)
q = Queue(connection=r)
print('Jobs in queue:', len(q.jobs))
started = StartedJobRegistry(queue=q)
failed = FailedJobRegistry(queue=q)
finished = FinishedJobRegistry(queue=q)
print('Started:', len(started))
print('Failed:', len(failed))
print('Finished:', len(finished))
