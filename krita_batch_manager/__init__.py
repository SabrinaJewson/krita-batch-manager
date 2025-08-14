from krita import Krita
import importlib
import krita
import os
import sys

from . import widget

class DockWidget(krita.DockWidget):
	w: widget.Widget

	def __init__(self) -> None:
		super().__init__()
		if (kr := Krita.instance()) is None: return
		self.setWindowTitle("Batch Manager")

		reload = None
		if os.path.isfile(os.path.join(os.path.dirname(os.path.abspath(__file__)), "dev_mode")):
			reload = lambda: self.reload(kr)
		self.w = widget.Widget(kr, reload)
		self.setWidget(self.w)

	def canvasChanged(self, canvas: krita.Canvas | None) -> None:
		self.w.canvas_changed(canvas)

	def reload(self, kr: Krita) -> None:
		for m in list(m for n, m in sys.modules.items() if n.startswith(f"{__name__}.")):
			importlib.reload(m)
		self.w = widget.Widget(kr, lambda: self.reload(kr))
		self.setWidget(self.w)

if (kr := Krita.instance()) is not None:
	pos = krita.DockWidgetFactoryBase.DockPosition.DockRight
	kr.addDockWidgetFactory(krita.DockWidgetFactory("Batch Manager", pos, DockWidget))
