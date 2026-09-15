"""TAK (Team Awareness Kit) integration for Oden.

``cot``      pure CoT (Cursor on Target) XML <-> report mapping, stdlib only
``bridge``   pytak connection: tx/rx queues, reconnect, settings
``listener`` inbound CoT -> filters -> Signal-shaped envelope -> pipelines
``hv_fields`` conventions shared by the ATAK "HV Rapporter" form family
``eight_s``  ATAK 8S report block -> ``7S RAPPORT`` text
``scrim``    ATAK SCRIM vehicle description -> ``SCRIM RAPPORT`` text
``marti``    the server file store: mission packages -> inbound CoT
``pref_package`` ATAK data package (.zip) -> connection settings, both kinds
``enrollment`` fetch + cache the client cert so pytak never re-enrolls
``redact``   keep configured passwords out of logs, errors and the GUI

``pytak`` is optional (``oden[tak]``) and only imported when TAK is enabled.

See docs/PLAN_TAK.md.
"""
