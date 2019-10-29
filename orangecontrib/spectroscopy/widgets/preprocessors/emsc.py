import numpy as np
import pyqtgraph as pg
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import QVBoxLayout, QLabel, QPushButton, QApplication, QStyle

from Orange.widgets import gui
from orangecontrib.spectroscopy.data import spectra_mean, getx
from orangecontrib.spectroscopy.preprocess import EMSC
from orangecontrib.spectroscopy.preprocess.emsc import ranges_to_weight_table
from orangecontrib.spectroscopy.widgets.gui import XPosLineEdit
from orangecontrib.spectroscopy.widgets.preprocessors.utils import BaseEditorOrange, \
    PreviewMinMaxMixin, layout_widgets, REFERENCE_DATA_PARAM


class EMSCEditor(BaseEditorOrange, PreviewMinMaxMixin):
    ORDER_DEFAULT = 2
    SCALING_DEFAULT = True
    OUTPUT_MODEL_DEFAULT = False

    def __init__(self, parent=None, **kwargs):
        super().__init__(parent, **kwargs)

        self.controlArea.setLayout(QVBoxLayout())

        self.reference = None
        self.preview_data = None

        self.order = self.ORDER_DEFAULT

        gui.spin(self.controlArea, self, "order", label="Polynomial order", minv=0, maxv=10,
                 controlWidth=50, callback=self.edited.emit)

        self.scaling = self.SCALING_DEFAULT
        gui.checkBox(self.controlArea, self, "scaling", "Scaling", callback=self.edited.emit)

        self.reference_info = QLabel("", self)
        self.controlArea.layout().addWidget(self.reference_info)

        self.output_model = self.OUTPUT_MODEL_DEFAULT
        gui.checkBox(self.controlArea, self, "output_model", "Output EMSC model as metas",
                     callback=self.edited.emit)

        self.ranges_box = gui.vBox(self.controlArea)  # container for ranges

        self.range_button = QPushButton("Select Region", autoDefault=False)
        self.range_button.clicked.connect(self.add_range_selection)
        self.controlArea.layout().addWidget(self.range_button)

        self.reference_curve = pg.PlotCurveItem()
        self.reference_curve.setPen(pg.mkPen(color=QColor(Qt.red), width=2.))
        self.reference_curve.setZValue(10)

        self.user_changed = False

    def _set_button_text(self):
        self.range_button.setText("Select Region"
                                  if self.ranges_box.layout().count() == 0
                                  else "Add Region")

    def add_range_selection(self):
        pmin, pmax = self.preview_min_max()
        lw = self.add_range_selection_ui()
        pair = self._extract_pair(lw)
        pair[0].position = pmin
        pair[1].position = pmax
        self.edited.emit()  # refresh output

    def add_range_selection_ui(self):
        linelayout = gui.hBox(self)
        pmin, pmax = self.preview_min_max()
        #TODO make the size appropriate so that the sidebar of the Preprocess Spectra doesn't change when the region is added
        mine = XPosLineEdit(label="")
        maxe = XPosLineEdit(label="")
        mine.set_default(pmin)
        maxe.set_default(pmax)
        for w in [mine, maxe]:
            linelayout.layout().addWidget(w)
            w.edited.connect(self.edited)
            w.focusIn.connect(self.activateOptions)

        remove_button = QPushButton(QApplication.style().standardIcon(QStyle.SP_DockWidgetCloseButton),
                                    "", autoDefault=False)
        remove_button.clicked.connect(lambda: self.delete_range(linelayout))
        linelayout.layout().addWidget(remove_button)

        self.ranges_box.layout().addWidget(linelayout)
        self._set_button_text()
        return linelayout

    def delete_range(self, box):
        self.ranges_box.layout().removeWidget(box)
        self._set_button_text()

        # remove selection lines
        curveplot = self.parent_widget.curveplot
        for w in self._extract_pair(box):
            if curveplot.in_markings(w.line):
                curveplot.remove_marking(w.line)

        self.edited.emit()

    def _extract_pair(self, container):
        return list(layout_widgets(container))[:2]

    def _range_widgets(self):
        for b in layout_widgets(self.ranges_box):
            yield self._extract_pair(b)

    def activateOptions(self):
        self.parent_widget.curveplot.clear_markings()
        if self.reference_curve not in self.parent_widget.curveplot.markings:
            self.parent_widget.curveplot.add_marking(self.reference_curve)

        for pair in self._range_widgets():
            for w in pair:
                if w.line not in self.parent_widget.curveplot.markings:
                    w.line.report = self.parent_widget.curveplot
                    self.parent_widget.curveplot.add_marking(w.line)


    def _set_range_parameters(self, params):
        ranges = params.get("ranges", [])
        rw = list(self._range_widgets())
        for i, (rmin, rhigh, weight) in enumerate(ranges):
            if i >= len(rw):
                lw = self.add_range_selection_ui()
                pair = self._extract_pair(lw)
            else:
                pair = rw[i]
            pair[0].position = rmin
            pair[1].position = rhigh

    def setParameters(self, params):
        if params:
            self.user_changed = True

        self.order = params.get("order", self.ORDER_DEFAULT)
        self.scaling = params.get("scaling", self.SCALING_DEFAULT)
        self.output_model = params.get("output_model", self.OUTPUT_MODEL_DEFAULT)
        self._set_range_parameters(params)

        self.update_reference_info()

    def parameters(self):
        parameters = super().parameters()
        parameters["ranges"] = []
        for pair in self._range_widgets():
            parameters["ranges"].append([float(pair[0].position), float(pair[1].position), 1.0])  # for now weight is always 1.0
        return parameters

    @classmethod
    def _compute_weights(cls, params):
        weights = None
        ranges = params.get("ranges", [])
        if ranges:
            weights = ranges_to_weight_table(ranges)
        return weights

    @classmethod
    def createinstance(cls, params):
        order = params.get("order", cls.ORDER_DEFAULT)
        scaling = params.get("scaling", cls.SCALING_DEFAULT)
        output_model = params.get("output_model", cls.OUTPUT_MODEL_DEFAULT)

        weights = cls._compute_weights(params)

        reference = params.get(REFERENCE_DATA_PARAM, None)
        if reference is None:
            return lambda data: data[:0]  # return an empty data table
        else:
            return EMSC(reference=reference, weights=weights, order=order, scaling=scaling, output_model=output_model)

    def set_reference_data(self, reference):
        self.reference = reference
        self.update_reference_info()

    def update_reference_info(self):
        if not self.reference:
            self.reference_curve.hide()
            self.reference_info.setText("Reference: missing!")
            self.reference_info.setStyleSheet("color: red")
        else:
            rinfo = "mean of %d spectra" % len(self.reference) \
                if len(self.reference) > 1 else "1 spectrum"
            self.reference_info.setText("Reference: " + rinfo)
            self.reference_info.setStyleSheet("color: black")
            X_ref = spectra_mean(self.reference.X)
            x = getx(self.reference)
            xsind = np.argsort(x)
            self.reference_curve.setData(x=x[xsind], y=X_ref[xsind])
            self.reference_curve.setVisible(self.scaling)

    def set_preview_data(self, data):
        self.preview_data = data
        # set all minumum and maximum defaults
        pmin, pmax = self.preview_min_max()
        for pair in self._range_widgets():
            pair[0].set_default(pmin)
            pair[1].set_default(pmax)
        if not self.user_changed:
            for pair in self._range_widgets():
                pair[0] = pmin
                pair[1] = pmax
            self.edited.emit()