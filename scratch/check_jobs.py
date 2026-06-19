from redis import Redis
from rq import Queue
r = Redis('redis', 6379, db=0)
q = Queue(connection=r)
print('Jobs:', q.jobs)
