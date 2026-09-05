import uuid

import pytest_asyncio
from temporalio import activity, workflow
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker
from temporalio.worker.workflow_sandbox import (SandboxedWorkflowRunner,
                                                SandboxRestrictions)

from python import config
from python.models.application import ApplicationFields
from python.models.core_banking import OpenAccountAck, OpenAccountRequest
from python.models.delivery import (NotifyRequest, NotifyResult,
                                    SendDocumentsRequest, SendDocumentsResult)
from python.models.documents import (DocumentManifest, DocumentRef,
                                     IngestRequest)
from python.models.extraction import ExtractionRequest, ExtractionResult
from python.workflows.onboarding import OnboardingWorkflow

# Set by Stubs.child(); read by StubExtractionChild inside the sandbox.
_ACTIVE = None


def manifest(attempt: int = 1) -> DocumentManifest:
    kinds = {"articles-of-incorporation": "articles_of_incorporation",
             "business-license": "business_license", "ein-letter": "ein_letter",
             "w9": "w9", "ownership-declaration": "ownership_declaration"}
    return DocumentManifest(refs=[
        DocumentRef(doc_id=d, kind=k, uri=f"acme-corp/{attempt}/{d}.pdf",
                    sha256="0" * 64, page_count=1) for d, k in kinds.items()])


def complete_application() -> ApplicationFields:
    """Every required field filled. Built from the gaps helper's expectations."""
    from datetime import date

    from tests.test_gaps import _complete_except_second_dob
    app = _complete_except_second_dob()
    app.beneficial_owners[1].dob = date(1985, 1, 1)
    return app


def application_with_the_gap() -> ApplicationFields:
    from tests.test_gaps import _complete_except_second_dob
    return _complete_except_second_dob()


class Stubs:
    """Hand-written test doubles — stubs, not fixtures (§16.0)."""

    def __init__(self):
        self.ingest_calls: list[int] = []
        self.extraction = ExtractionResult(application=complete_application(),
                                           gaps=[], iterations=2, escalated=False)
        self.child_raises = False
        self.open_account_acks: list[OpenAccountAck] = []
        self.notifications: list[dict] = []

    def activities(self):
        """Every stub annotates its argument. Without the annotation the
        converter has nothing to build from and hands the activity a dict --
        which fails, retries forever, and presents as a hung test."""
        outer = self

        @activity.defn(name="ingest_documents")
        async def ingest(req: IngestRequest) -> DocumentManifest:
            outer.ingest_calls.append(req.attempt)
            return manifest(req.attempt)

        @activity.defn(name="open_account")
        async def open_account(req: OpenAccountRequest) -> OpenAccountAck:
            if outer.open_account_acks:
                return outer.open_account_acks.pop(0)
            return OpenAccountAck(request_id="REQ-1", status="accepted")

        @activity.defn(name="send_documents")
        async def send(req: SendDocumentsRequest) -> SendDocumentsResult:
            return SendDocumentsResult(packet_uri="acme-corp/CL-1.txt", page_count=1)

        @activity.defn(name="notify")
        async def notify_(req: NotifyRequest) -> NotifyResult:
            outer.notifications.append(req.model_dump(mode="json"))
            return NotifyResult(delivered_to=list(req.recipients))

        return [ingest, open_account, send, notify_]

    def child(self):
        """The stub child must be a module-level class -- the SDK refuses
        `@workflow.run` on a local one -- so it reads the active Stubs through
        a module global, and `tests` is passed through the sandbox below so the
        two see the same object."""
        global _ACTIVE
        _ACTIVE = self
        return StubExtractionChild


@workflow.defn(name="ExtractionAgentWorkflow")
class StubExtractionChild:
    @workflow.run
    async def run(self, req: ExtractionRequest) -> ExtractionResult:
        assert _ACTIVE is not None, "Stubs.child() was never called"
        if _ACTIVE.child_raises:
            raise ApplicationError("extraction blew up", non_retryable=True)
        return _ACTIVE.extraction


@pytest_asyncio.fixture
async def skip_env():
    """Time-skipping environments CANNOT be shared between tests (§16.3), so
    this is function-scoped like `env` and never reused."""
    async with await WorkflowEnvironment.start_time_skipping(
            data_converter=config.build_data_converter()) as e:
        yield e


@pytest_asyncio.fixture
async def env():
    async with await WorkflowEnvironment.start_local(
            data_converter=config.build_data_converter()) as e:
        yield e


async def run_worker(env, stubs: Stubs):
    queue = str(uuid.uuid4())
    worker = Worker(
        env.client, task_queue=queue,
        workflows=[OnboardingWorkflow, stubs.child()],
        activities=stubs.activities(),
        # `tests` passes through so the stub child sees the live Stubs object.
        # The workflow under test stays sandboxed.
        workflow_runner=SandboxedWorkflowRunner(
            restrictions=SandboxRestrictions.default.with_passthrough_modules(
                "tests")))
    return queue, worker
