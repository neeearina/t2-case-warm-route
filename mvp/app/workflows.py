from datetime import timedelta
from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError


@workflow.defn
class RefreshCity:
    @workflow.run
    async def run(self) -> dict:
        results = {}
        for source in ('weather', 'mobility', 'transport', 'reports'):
            try:
                results[source] = await workflow.execute_activity('ingest',source,
                    start_to_close_timeout=timedelta(seconds=60),
                    schedule_to_close_timeout=timedelta(minutes=3),
                    retry_policy=RetryPolicy(initial_interval=timedelta(seconds=5),maximum_interval=timedelta(seconds=30),maximum_attempts=3))
            except ActivityError:
                results[source] = 'failed'
        await workflow.execute_activity('maintain',start_to_close_timeout=timedelta(seconds=60),
            schedule_to_close_timeout=timedelta(minutes=3),retry_policy=RetryPolicy(maximum_attempts=3))
        return results
