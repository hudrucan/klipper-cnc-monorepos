import logging

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from panels.menu import Panel as MenuPanel


class Panel(MenuPanel):
    def __init__(self, screen, title, items=None):
        super().__init__(screen, title, items)
        self.main_menu = Gtk.Grid(
            row_homogeneous=True, column_homogeneous=True, hexpand=True, vexpand=True
        )
        scroll = self._gtk.ScrolledWindow()

        logging.info("### Making CNC MainMenu")

        columns = 3 if self._screen.vertical_mode else 4
        self.labels["menu"] = self.arrangeMenuItems(items, columns, True)
        scroll.add(self.labels["menu"])
        self.labels["status"] = self.create_status_panel()
        if self._screen.vertical_mode:
            self.main_menu.attach(self.labels["status"], 0, 0, 1, 1)
            self.main_menu.attach(scroll, 0, 1, 1, 3)
        else:
            self.main_menu.attach(self.labels["status"], 0, 0, 1, 1)
            self.main_menu.attach(scroll, 1, 0, 3, 1)
        self.content.add(self.main_menu)

    def create_status_panel(self):
        status = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        status.get_style_context().add_class("heater-list")

        title = Gtk.Label(label=_("Temperature"), halign=Gtk.Align.START)
        title.get_style_context().add_class("temperature_entry")
        status.pack_start(title, False, False, 0)

        devices = self._printer.get_temp_devices()
        if not devices:
            empty = Gtk.Label(label=_("No temperature sensors"), halign=Gtk.Align.START)
            status.pack_start(empty, False, False, 0)
            return status

        for device in devices:
            name = device.split(" ", 1)[1] if " " in device else device
            label = self._gtk.Button("heat-up", self.prettify(name), None, self.bts)
            label.set_alignment(0, 0.5)
            label.connect(
                "clicked",
                self.menu_item_clicked,
                {"panel": "temperature", "extra": device},
            )
            label.get_style_context().add_class("frame-item")
            self.labels[f"temp_{device}"] = label
            status.pack_start(label, False, False, 0)
        return status

    def process_update(self, action, data):
        if action != "notify_status_update":
            return
        for device in self._printer.get_temp_devices():
            temp = self._printer.get_stat(device, "temperature")
            if temp in ({}, None):
                continue
            label = self.labels.get(f"temp_{device}")
            if label is None:
                continue
            name = device.split(" ", 1)[1] if " " in device else device
            label.set_label(f"{self.prettify(name)}  {temp:.0f}°")
