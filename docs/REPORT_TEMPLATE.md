# Report Template Documentation

Oden uses Jinja2 templates to format Signal reports as Markdown files. This allows customization of the report format without modifying code.

## Template Files

Templates are located in the `templates/` directory:

| File | Purpose |
|------|---------|
| `report.md.j2` | Template for new reports |
| `append.md.j2` | Template for appended messages (reply/++) |

## Placeholders

### Mandatory Placeholders

These placeholders are always available and will always have values:

| Placeholder | Type | Description | Example |
|-------------|------|-------------|---------|
| `{{ fileid }}` | string | Unique file identifier | `161430-46701234567-Nicklas` |
| `{{ group_title }}` | string | Signal group name | `7s-test` |
| `{{ group_id }}` | string | Signal group identifier | `abc123...` |
| `{{ tnr }}` | string | Timestamp in DDHHMM format | `161430` |
| `{{ timestamp_iso }}` | string | Full ISO 8601 timestamp | `2026-02-05T16:14:30+01:00` |
| `{{ sender_display }}` | string | Formatted sender string | `Nicklas ( [[+46701234567]])` |

### Optional Placeholders

These placeholders may be empty/null. Use Jinja2 conditionals to handle them:

| Placeholder | Type | Description | Condition |
|-------------|------|-------------|-----------|
| `{{ sender_name }}` | string\|null | Sender's display name | Available if sender has a profile name |
| `{{ sender_number }}` | string\|null | Sender's phone number | Available if number is visible |
| `{{ lat }}` | string\|null | Latitude coordinate | Present if message contains Google Maps URL |
| `{{ lon }}` | string\|null | Longitude coordinate | Present if message contains Google Maps URL |
| `{{ quote_formatted }}` | string\|null | Pre-formatted quote block | Present when replying to a message |
| `{{ message }}` | string\|null | Message text (with regex links applied) | Present if message has text content |
| `{{ attachments }}` | list[string] | List of Obsidian embed links | Present if message has attachments |

## Jinja2 Syntax

### Conditionals

Use `{% if %}` blocks for optional content:

```jinja
{% if message %}

## Meddelande

{{ message }}
{% endif %}
```

### Loops

Use `{% for %}` for lists like attachments:

```jinja
{% if attachments %}

## Bilagor

{% for link in attachments -%}
{{ link }}
{% endfor -%}
{% endif %}
```

### Whitespace Control

- Use `{%-` to strip whitespace before the tag
- Use `-%}` to strip whitespace after the tag

Example (no extra blank lines):
```jinja
{% if lat and lon -%}
locations: ""
{% endif -%}
```

## Default Templates

### report.md.j2

```jinja
---
fileid: {{ fileid }}
{% if lat and lon -%}
locations: ""
{% endif -%}
---

# {{ group_title }}

TNR: {{ tnr }}

Avsändare: {{ sender_display }}

Grupp: [[{{ group_title }}]]

Grupp id: {{ group_id }}
{% if lat and lon %}
[Position](geo:{{ lat }},{{ lon }})
{% endif %}
{% if quote_formatted %}
{{ quote_formatted }}
{% endif %}
{% if message %}

## Meddelande

{{ message }}
{% endif %}
{% if attachments %}

## Bilagor

{% for link in attachments -%}
{{ link }}
{% endfor -%}
{% endif %}
```

### append.md.j2

```jinja
---

TNR: {{ tnr }} ({{ timestamp_iso }})
Avsändare: {{ sender_display }}
{% if message %}

{{ message }}
{% endif %}
{% if attachments %}

## Bilagor

{% for link in attachments -%}
{{ link }}
{% endfor -%}
{% endif %}
```

## Customization

To customize templates, edit the files in `templates/`. Changes take effect on the next message received.

**Note:** When running as a bundled application (PyInstaller build), templates are bundled inside the app. To customize, you'll need to rebuild or modify the templates before building.

## Example Output

Given a message with:
- Group: `7s-test`
- Sender: `Nicklas` (`+46701234567`)
- Message: `Test message`
- Timestamp: `2026-02-05 16:14:30`

The output would be:

```markdown
---
fileid: 161430-46701234567-Nicklas
---

# 7s-test

TNR: 161430

Avsändare: Nicklas ( [[+46701234567]])

Grupp: [[7s-test]]

Grupp id: abc123...

## Meddelande

Test message
```
