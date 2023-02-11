#!/usr/bin/env python3
#
# Copyright 2023 Red Hat, Inc.
#
# Authors:
#     Alexander Lougovksi <alougovs@redhat.com>
#
# This work is licensed under the MIT License.  Please see the LICENSE file or
# http://opensource.org/licenses/MIT.

from api.models import Message, QueuedSeries

from .patchewtest import PatchewTestCase, main


class CollaborativeTest(PatchewTestCase):
    def setUp(self):
        self.testuser = self.create_user("test", "1234", groups=["importer"])
        self.testuser2 = self.create_user("test2", "1234", groups=["maintainers"])
        self.testuser3 = self.create_user("test3", "1234", groups=["maintainers"])
        self.create_superuser()
        self.cli_login()
        self.p = self.add_project("QEMU", "qemu-devel@nongnu.org")
        self.p.maintainers.add(self.testuser)
        self.p.maintainers.add(self.testuser2)
        self.p.maintainers.add(self.testuser3)
        self.p.config = {
            "collaborative": {
                "queues": ["accept", "reject", "RHEL-\d+\.\d+"]
            }
        }
        self.p.save()


    def test_accept_query(self):
        self.cli_import("0001-simple-patch.mbox.gz")
        msg = Message.objects.first()

        self.client.post("/login/", {"username": "test", "password": "1234"})
        self.client.post("/QEMU/" + msg.message_id + "/mark-as-accepted/", {"next": "/"})
        query = QueuedSeries.objects.filter(message=msg, name="accept")
        assert query.count() == self.p.maintainers.count()
        self.client.post("/QEMU/" + msg.message_id + "/clear-reviewed/", {"next": "/"})
        assert QueuedSeries.objects.filter(message=msg, name="accept").count() == 0

    def test_reject_query(self):
        self.cli_import("0001-simple-patch.mbox.gz")
        msg = Message.objects.first()

        self.client.post("/login/", {"username": "test", "password": "1234"})
        self.client.post("/QEMU/" + msg.message_id + "/mark-as-rejected/", {"next": "/"})
        query = QueuedSeries.objects.filter(message=msg, name="reject")
        assert query.count() == self.p.maintainers.count()
        self.client.post("/QEMU/" + msg.message_id + "/clear-reviewed/", {"next": "/"})
        assert QueuedSeries.objects.filter(message=msg, name="reject").count() == 0
    
    def test_rhelxx_query(self):
        self.cli_import("0001-simple-patch.mbox.gz")
        msg = Message.objects.first()
        queue = "RHEL-8.9"

        self.client.post("/login/", {"username": "test", "password": "1234"})
        self.client.post("/QEMU/" + msg.message_id + "/add-to-queue/", {"queue": queue,"next": "/"})
        query = QueuedSeries.objects.filter(message=msg, name=queue)
        assert query.count() == self.p.maintainers.count()
        self.client.post("/QEMU/" + msg.message_id + "/drop-from-queue/" + queue + "/", {"next": "/"})
        assert QueuedSeries.objects.filter(message=msg, name=queue).count() == 0

    def test_random_query(self):
        self.cli_import("0001-simple-patch.mbox.gz")
        msg = Message.objects.first()
        queue = "CentOS-9"

        self.client.post("/login/", {"username": "test", "password": "1234"})
        self.client.post("/QEMU/" + msg.message_id + "/add-to-queue/", {"queue": queue,"next": "/"})
        assert QueuedSeries.objects.filter(message=msg, name=queue).count() == 1
        self.client.post("/QEMU/" + msg.message_id + "/drop-from-queue/" + queue + "/", {"next": "/"})
        assert QueuedSeries.objects.filter(message=msg, name=queue).count() == 0


if __name__ == "__main__":
    main()
