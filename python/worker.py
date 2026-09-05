"""Worker entrypoint. Selects the call_llm implementation at STARTUP -- never
by an `if` inside the workflow, which would be a determinism hazard and would
make the two modes non-replay-compatible (§3 of the decisions, §8.3)."""
from __future__ import annotations

import asyncio
import logging

from temporalio.client import Client
from temporalio.worker import Worker

from python import config
from python.activities.core_banking import open_account
from python.activities.delivery import notify, send_documents
from python.activities.ingest import ingest_documents
from python.activities.llm import fixture_call_llm, live_call_llm
from python.workflows.extraction import ExtractionAgentWorkflow
from python.workflows.onboarding import OnboardingWorkflow


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    s = config.settings()
    call_llm = fixture_call_llm if s.fixture_mode else live_call_llm
    logging.info("call_llm implementation: %s", call_llm.__name__)

    client = await Client.connect(s.temporal_address,
                                  data_converter=config.build_data_converter())
    worker = Worker(
        client, task_queue=s.task_queue,
        workflows=[OnboardingWorkflow, ExtractionAgentWorkflow],
        activities=[ingest_documents, call_llm, open_account,
                    send_documents, notify])
    logging.info("worker polling %s", s.task_queue)
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
