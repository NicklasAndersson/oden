"""TAK (Team Awareness Kit) integration for Oden.

``cot``      pure CoT (Cursor on Target) XML <-> report mapping, stdlib only
``bridge``   pytak connection: tx/rx queues, reconnect, settings
``listener`` inbound CoT -> filters -> Signal-shaped envelope -> pipelines
``eight_s``  ATAK 8S report block -> ``7S RAPPORT`` text

``pytak`` is optional (``oden[tak]``) and only imported when TAK is enabled.

See docs/PLAN_TAK.md.
"""
