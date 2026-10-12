# Create a configured Jira issue

Parse the requested issue type (epic, story or task), title, project, optional parent,
description and assignee. Inspect authorized project configuration for defaults; do
not assume a specific tenant, project prefix, credentials database or script.

Discover the actual Jira capability and its schema. Confirm the selected project and
supported issue types/parent relationship using read-only evidence. Prepare the issue
content first. Ask only for missing required information, keeping independent drafting
work moving. Creating a requested issue is authorized; unrelated messages/updates are not.

Use the actual API/tool to create it, with an explicitly requested assignee or the
configured current-user convention. Verify the returned key, URL and fields. If no
Jira connector or runnable project integration exists, report that no issue was created
and provide the ready-to-use content. Never claim a draft is a live issue.
