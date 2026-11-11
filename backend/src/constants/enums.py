from enum import StrEnum
class Role(StrEnum):
 ADMIN='admin'
 ANALYST='analyst'
 VIEWER='viewer'
class RunStatus(StrEnum):
 QUEUED='queued'
 RUNNING='running'
 SUCCEEDED='succeeded'
 FAILED='failed'
class PlanStatus(StrEnum):
 DRAFT='draft'
 APPROVED='approved'
 REJECTED='rejected'
class FindingStatus(StrEnum):
 REVIEW='review'
 QUIET='quiet'
