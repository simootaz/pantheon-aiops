"""Argus - detects metric anomalies and correlates them into candidate Findings.

Phase: 1 - Contracts & First Agent Path
"""

# No re-export. `core/orchestrator/__init__.py` imports the class directly when it
# registers it, so a second name for the same object would be one more place to
# keep in step.
