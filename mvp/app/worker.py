import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from temporalio.client import (Client, Schedule, ScheduleActionStartWorkflow, ScheduleIntervalSpec,
    ScheduleSpec, SchedulePolicy, ScheduleOverlapPolicy, ScheduleAlreadyRunningError, ScheduleUpdate)
from temporalio.worker import Worker
from app.config import settings
from app.activities import ingest, maintain
from app.workflows import RefreshCity

QUEUE = 'warm-route'
SCHEDULE = 'refresh-city'


async def main():
    logging.basicConfig(level=logging.INFO)
    client = await Client.connect(settings.temporal_address)
    schedule = Schedule(action=ScheduleActionStartWorkflow(RefreshCity.run,id='refresh-city-run',task_queue=QUEUE),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(seconds=settings.poll_seconds))]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP,catchup_window=timedelta(minutes=1)))
    try:
        await client.create_schedule(SCHEDULE,schedule,trigger_immediately=True)
    except ScheduleAlreadyRunningError:
        await client.get_schedule_handle(SCHEDULE).update(lambda _: ScheduleUpdate(schedule=schedule))
    with ThreadPoolExecutor(max_workers=4) as executor:
        worker = Worker(client,task_queue=QUEUE,workflows=[RefreshCity],activities=[ingest,maintain],activity_executor=executor)
        await worker.run()


if __name__ == '__main__':
    asyncio.run(main())
