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
        self.main_menu.attach(scroll, 0, 0, 1, 1)
        self.content.add(self.main_menu)
