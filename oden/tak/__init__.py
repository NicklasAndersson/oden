"""TAK (Team Awareness Kit) integration for Oden.

``cot``      pure CoT (Cursor on Target) XML <-> report mapping, stdlib only
``bridge``   pytak connection: tx/rx queues, reconnect, settings
``listener`` inbound CoT -> filters -> Signal-shaped envelope -> pipelines
``eight_s``  ATAK 8S report block -> ``7S RAPPORT`` text
``pref_package`` ATAK data package (.zip) -> connection settings, both kinds
``enrollment`` fetch + cache the client cert so pytak never re-enrolls
``redact``   keep configured passwords out of logs, errors and the GUI

``pytak`` is optional (``oden[tak]``) and only imported when TAK is enabled.

See docs/PLAN_TAK.md.
"""
