#!/usr/bin/env python3
#
# Copyright 2023 Red Hat, Inc.
#
# Authors:
#     Alexander Lougovski <alougovs@redhat.com>
#
# This work is licensed under the MIT License.  Please see the LICENSE file or
# http://opensource.org/licenses/MIT.

from mod import PatchewModule
from mbox import addr_db_to_rest, parse_address
from event import register_handler, emit_event
from api.models import Message, QueuedSeries
from api.rest import PluginMethodField

from django.urls import reverse
from django.utils.html import format_html

import rest_framework
import re
import schema


_default_config = """
[collaborative]
"""


class CollaborativeModule(PatchewModule):
    """

Documentation
-------------

This module is configured in "INI" style.

It has only one section named `[collaborative]`. The only supported option is queue regexs. 
Listed queue names will be shared among all maintainers in the project:

    [collaborative]
"""

    name = "collaborative"

    queue_schema = schema.ArraySchema(
        "{name}",
        "Queue Config",
        desc="Configurtaion for individual queue regex",
        members=[
            schema.StringSchema(
                "regex",
                "RegEx",
                desc="RegEx for the queue",
                required=True,
            ),
            schema.StringSchema(
                "title",
                "Title",
                desc="Title to display",
                required=True,
            ),
            schema.StringSchema(
                "char",
                "Char",
                desc="Which character will be used for tagging",
                required=True,
            ),
            schema.StringSchema(
                "type",
                "Type",
                desc="Type of the tag (success, failure)",
                required=True,
            ),
            schema.IntegerSchema(
                "group",
                "Group Index",
                desc="Group index in the regex",
                required=False,
                default=0,
            )
        ],
    )
    project_config_schema = schema.ArraySchema(
        "collaborative",
        desc="Configuration for collaborative module",
        members=[
            schema.MapSchema(
                "queues", 
                "Collaborative configuration", 
                desc="List of regexs for collaborative queues", 
                item = queue_schema,
            )
        ],
    )

  #  default_config = _default_config

    def __init__(self):
        register_handler("MessageQueued", self.on_message_queued)
        register_handler("MessageDropped", self.on_message_dropped)
        
    def _get_queues(self, project):
        return list(self.get_project_config(project).get("queues", {}).values())

    def _is_special_queue(self, name, project):       
        regexs = [i["regex"] for i in self._get_queues(project)]
        combined_regex = "(" + ")|(".join(regexs) + ")"
        return re.match(combined_regex, name)

    def on_message_queued(self, event, user, message, queue):
        if self._is_special_queue(queue.name, message.project) and user in message.project.maintainers.all():
            for mainainer in message.project.maintainers.all():
                if mainainer != user:
                    q, created = QueuedSeries.objects.get_or_create(
                        user=mainainer, message=message, name=queue.name
                        )
                    if created:
                        emit_event("MessageQueued", user=user, message=message, queue=q)

    def on_message_dropped(self, event, user, message, queue):
        if self._is_special_queue(queue.name, message.project) and user in message.project.maintainers.all():
            events = []
            for l in QueuedSeries.objects.filter(message=message, name=queue.name):
                if l.user in message.project.maintainers.all() and l.user != user: 
                    events.append({"user": l.user, "message": l.message, "queue": l})
                    l.delete()
            for ev in events:
                emit_event("MessageDropped", **ev)
                    
    def prepare_message_hook(self, request, message, for_message_view):

        queues = QueuedSeries.objects.filter(message=message)
        if queues.count() == 0:
            message.status_tags.append(
                {
                    "title": "Neiter tracked or accepted",
                    "type": "warning",
                    "char": "!"
                }
            )
        else:
            status = {}
            tag = {}
            prio = 0        
            for r in queues:
                if self._is_special_queue(r.name, message.project):
                    for q in self._get_queues(message.project):
                        match = re.match(q['regex'], r.name)
                        group = q.get('group', 0)
                        if match:
                            title = q['title']
                            if '%s' in title:
                                title = title % match.group(group)
                            char = q['char']
                            if '%s' in char:
                                char = char % match.group(group)
                            tag={
                                    "title": title ,
                                    "type": q['type'],
                                    "char": char
                                }
                            prio = 2
                elif r.name != "watched":
                    if prio < 1:
                        tag={
                                "title": "Tracked by maintainers",
                                "type": "secondary",
                                "char": "T",
                                "row_class": "tracked"
                            }
                        status={
                                    "icon": "fa-exclamation-circle",  
                                    "html": format_html(
                                        'Series is already tracked by {}',
                                        r.user,
                                    ),
                                }
                        prio = 1
            if tag:
                message.status_tags.append(tag)
            if status:
                message.extra_status.append(status)

    def prepare_project_hook(self, request, project):
        if not project.maintained_by(request.user):
            return
        project.extra_info.append(
            {
                "title": "Collaborative configuration",
                "class": "info",
                "content_html": self.build_config_html(request, project),
            }
        )