"""protokflow storage models; importing this package registers all tables."""

from backend.app.protokflow.model.candidate import Candidate
from backend.app.protokflow.model.design_system import DesignSystem
from backend.app.protokflow.model.design_token import DesignToken
from backend.app.protokflow.model.export import Export
from backend.app.protokflow.model.prototype_run import PrototypeRun
from backend.app.protokflow.model.schema_meta import SchemaMeta
from backend.app.protokflow.model.slot_content import SlotContent
from backend.app.protokflow.model.token_patch import TokenPatch

__all__ = [
    "Candidate",
    "DesignSystem",
    "DesignToken",
    "Export",
    "PrototypeRun",
    "SlotContent",
    "SchemaMeta",
    "TokenPatch",
]
