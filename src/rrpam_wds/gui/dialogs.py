from rrpam_wds.gui import set_pyqt_api   # isort:skip # NOQA

import logging
import math
import random
import sys

from guidata.configtools import add_image_module_path
from guidata.configtools import get_icon
from guiqwt.builder import make
from guiqwt.config import CONF
from guiqwt.plot import CurveDialog
from guiqwt.styles import style_generator
from guiqwt.styles import update_style_attr
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure
from numpy import arange
from numpy import array
from numpy import interp
from numpy import linspace
from numpy import max
from numpy import min
from numpy import pi
from numpy import sin
from PyQt5 import QtCore
from PyQt5 import QtGui
from PyQt5 import QtWidgets
from PyQt5.QtCore import QObject
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtCore import pyqtSlot
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import QAction
from PyQt5.QtWidgets import QApplication
from PyQt5.QtWidgets import QDialog
from PyQt5.QtWidgets import QFrame
from PyQt5.QtWidgets import QMainWindow
from PyQt5.QtWidgets import QMdiArea
from PyQt5.QtWidgets import QPlainTextEdit
from PyQt5.QtWidgets import QSizePolicy
from PyQt5.QtWidgets import QSlider
from PyQt5.QtWidgets import QSplitter
from PyQt5.QtWidgets import QVBoxLayout

import rrpam_wds.constants as c
import rrpam_wds.gui.subdialogs
import rrpam_wds.gui.utils as u
from rrpam_wds.constants import curve_colors
from rrpam_wds.constants import units
from rrpam_wds.gui import _property_widget
from rrpam_wds.gui import monkey_patch_guiqwt_guidata
from rrpam_wds.gui.custom_toolbar_items import ResetZoomTool
from rrpam_wds.logger import EmittingLogger
from rrpam_wds.logger import setup_logging
from rrpam_wds.project_manager import ProjectManager as PM

# there are some changes to the guiqwt classes to be done. It is not easy to do this by subclassing, as
# we need to user make.* facotry
monkey_patch_guiqwt_guidata._patch_all()
# show guiqwt where the images are.
add_image_module_path("rrpam_wds.gui", "images")
# this how we change an option
CONF.set("plot", "selection/distance", 10.0)
# todo: This has to be saved as project's setting file (CONF.save provides that facility)

STYLE = style_generator()


class PropertyGroupGUI(QObject):

    logger = logging.getLogger()

    def __init__(self, frame):
        self.active = False
        self.frame = frame

        super(PropertyGroupGUI, self).__init__()

    def show(self):
        self.active = True
        self.frame.show()

    def hide(self):
        self.active = False
        self.frame.hide()

    def _selected_change_color(self, select):
        self.my_selected.setProperty("selected", False)
        self.my_selected.setStyleSheet("""
                       /* other rules go here */
                       QCheckBox[selected="true"] {background-color: yellow};
                       QCheckBox[selected="false"] {background-color: palette(base)};
                        """)
        if(select):
            self.my_selected.setProperty('selected', "true")
        else:
            self.my_selected.setProperty('selected', "false")

        self.my_selected.style().unpolish(self.my_selected)
        self.my_selected.style().polish(self.my_selected)

    def selected(self):
        if(hasattr(self, "my_selected")):
            self.logger.info("returning my (%s) checkbox state" % self)
            return self.my_selected.isChecked()
        self.logger.info("No checkbox in me (%s), so returning False for selected state." % self)
        return False

    def select(self, select=True):
        if(hasattr(self, "my_selected")):
            self.logger.info("making me (%s) selected=%s" % (self, select))
            self.my_selected.setChecked(select)
        else:
            self.logger.info("No checkbox in me (%s). So ignoring select request." % self)


class LogDialog(QDialog):

    def __init__(self, parent=None):
        super(LogDialog, self).__init__()
        self.parent = parent
        self.logwindow = QPlainTextEdit(parent=self.parent)
        self.logwindow.setReadOnly(True)
        self.logwindow.setStyleSheet("QPlainTextEdit {background-color:gray}")
        layout = QVBoxLayout(self)
        layout.addWidget(self.logwindow)
        self.setWindowIcon(get_icon("log_file.png"))
        self.setWindowTitle("Log record")

    @pyqtSlot(object)
    def reciever(self, object):
        # print("I Got: ", str(object))
        if (QApplication.instance()):
            # ^^ this is done as a safeguard of segfaults when called many tests together in pytest
            # Sometimes this method is called when there is no vailid Qapplication instance
            #  then appendPlainText segfaults.
            self.logwindow.appendPlainText(object)

    def get_text(self):
        return self.logwindow.toPlainText()

    def closeEvent(self, evnt):
        evnt.ignore()
        self.parent.hide_log_window()


class DataWindow(QDialog):
    groups_changed = pyqtSignal(list)
    myselectionchanged_signal = pyqtSignal(object)

    def __init__(self, mainwindow, parent=None):

        super(DataWindow, self).__init__(parent=parent)
        self.setWindowTitle("Data Editor")
        self.setWindowIcon(get_icon("data.png"))
        self.initialize_assetgroups()
        self.initalize_assign_asset_groups()
        self.selected_holder = mainwindow.selected_holder
        self.setup_ui()
        self.customize_ui()
        self.connect_signals()
        self._update_all()  # always call this at the end of _init_

    def draw_network(self, links):
        logger = logging.getLogger()
        if(not links):
            logger.info("Links sent was None. Ignoring request to draw!")
            return
        logger.info("Drawing links (%s)" % links)

        for link in links:
            self.add_assign_asset_item(link.id)
        spacerItem = QtWidgets.QSpacerItem(
            20,
            40,
            QtWidgets.QSizePolicy.Minimum,
            QtWidgets.QSizePolicy.Expanding)
        self.ui.assign_asset_item_parent_layout.addItem(spacerItem)

    def _update_all(self):
        self._set_no_groups(1)

    def get_items(self):
        return self.myplotitems.values()

    def select_some_items(self, list_):
        logger = logging.getLogger()
        try:
            for target in self.myplotitems.values():
                target.select(False)
            for target in list_:
                target.select()
        except Exception as e:
            logger.exception("Error at select_some_items (%s) " % e)

    def myselectionchanged(self, state):
        logger = logging.getLogger()
        logger.info("Passing on a signal with my reference...")
        self.myselectionchanged_signal.emit(self)

    def initalize_assign_asset_groups(self):
        self.myplotitems = {}
        if(hasattr(self, 'ui')):
            layout = self.ui.assign_asset_item_parent_layout
            self._delete_all_children_in_layout(layout)

    def initialize_assetgroups(self):
        logger = logging.getLogger()
        logger.info("Initializing assetgrouplist=[] and activenumberofgroups=0 ")
        self.assetgrouplist = []
        self.activenumberofgroups = 0
        if(hasattr(self, 'ui')):
            layout = self.ui.assetgroup_container_parent_layout
            self._delete_all_children_in_layout(layout)

    def _delete_all_children_in_layout(self, layout):
        for i in reversed(range(layout.count())):
            w = layout.itemAt(i).widget()
            if(w):
                w.hide()
                w.setParent(None)
                w.deleteLater()

    def setup_ui(self):
        self.ui = _property_widget.Ui_projectDataWidget()
        self.ui.setupUi(self)
        # self.ui.no_groups.valueChanged.disconnect()

    def connect_signals(self):
        self.ui.no_groups.valueChanged.connect(self._set_no_groups)
        self.groups_changed.connect(self._update_grouptocopy)
        self.myselectionchanged_signal.connect(self.selected_holder)

    def _update_grouptocopy(self, listofgroups):
        logger = logging.getLogger()
        logger.info("Updating grouptocopy choices.")
        self.ui.grouptocopy.clear()
        self.ui.grouptocopy.addItems(listofgroups)

    def customize_ui(self):
        self.spacerItem1 = QtWidgets.QSpacerItem(
            40,
            20,
            QtWidgets.QSizePolicy.Minimum,
            QtWidgets.QSizePolicy.Expanding)

    def get_plot(self):
        """This weird method is here so that this object confirms to the pattern
        of other sub-window types (which all have plots). In this case we just return a referene
        to this object. """
        return self

    def get_selected_items(self):
        """we are mimicking get_selected_items method of guiqwt.BasePlot widget"""
        return [x for x in self.myplotitems.values() if x.selected()]

    def get_information(self, all=False):
        """This method returns active data of assetgrouplist (activenumberofgroups) - e.g. for calculations.
        if all=True, then it will return ALL items in assetgrouplist (e.g. for saving)"""
        if (not all):
            gr = [(float(x.A.text()), float(x.N0.text()), x.age.value())
                  for x in self.assetgrouplist[:self.activenumberofgroups]]
            return self.activenumberofgroups, gr
        else:
            return self.activenumberofgroups, [(float(x.A.text()), float(x.N0.text()), x.age.value()) for x in self.assetgrouplist]

    def set_information(self, results_):
        active = int(results_[0])  # just in case it is a string!
        results = results_[1]
        self.initialize_assetgroups()
        for ct, value in enumerate(results):
            self.add_assetgroup(ct, value)
        self.ui.no_groups.setValue(active)
        self._set_no_groups(active)
        # this is needed, as ^^ we change the value manually, signal does not
        # fire.

    def _set_no_groups(self, ngroups):
        # first remove that spacer
        self.ui.assetgroup_container_parent_layout.removeItem(self.spacerItem1)
        need = ngroups - self.activenumberofgroups
        self.activenumberofgroups = ngroups
        logger = logging.getLogger()
        if(need > 0):
            logger.info("Need %d number of asset groups more." % need)
            needtocreate = ngroups - len(self.assetgrouplist)
            st = len(self.assetgrouplist)
            if(needtocreate > 0):
                logger.info("Need to create %d new" % needtocreate)
                for i in range(needtocreate):
                    self.add_assetgroup(st + i)
        # now unhide
        logger.info("Unhiding from 0 to %d" % ngroups)
        for i in range(ngroups):
            self.assetgrouplist[i].show()
        logger.info("Hiding from %d to %d" % (ngroups, len(self.assetgrouplist)))
        for i in range(ngroups, len(self.assetgrouplist)):
            self.assetgrouplist[i].hide()

        # now add the spacer
        self.ui.assetgroup_container_parent_layout.addItem(self.spacerItem1)
        items = list(self.ui.assetgroup_container_parent_layout.itemAt(i)
                     for i in range(self.ui.assetgroup_container_parent_layout.count()))
        logger.info("List of widgets: %s " % items)
        logger.info("Sending signal: group choices updated.")
        self.groups_changed.emit([self._getgroupname(i) for i in range(self.activenumberofgroups)])

    def add_plot_item_to_record(self, id_, item):
        """All the plot items register here by calling this method. See also: remove_plot_item_from_record"""
        # TODO : CurveDialogWithClosable currently copies this function
        # need to implement multiple inheritance and make DRY
        self.myplotitems[id_] = item

    def remove_plot_item_from_record(self, id_):
        """When removing a plot item it should be notified to this function. See also: add_plot_item_to_record """
        # TODO : CurveDialogWithClosable currently copies this function
        # need to implement multiple inheritance and make DRY
        del self.myplotitems[id_]

    def add_assign_asset_item(self, id_):
        ag = PropertyGroupGUI(frame=QFrame())
        ag.assign_asset_item = QtWidgets.QFrame(self.ui.scrollAreaWidgetContents)
        ag.assign_asset_item.setObjectName("assign_asset_item")
        ag.indiviual_asset_container_layout_4 = QtWidgets.QHBoxLayout(ag.assign_asset_item)
        ag.indiviual_asset_container_layout_4.setObjectName("indiviual_asset_container_layout_4")
        ag.label_8 = QtWidgets.QLabel(ag.assign_asset_item)
        ag.label_8.setMaximumSize(QtCore.QSize(50, 16777215))
        ag.label_8.setObjectName("label_8")
        ag.indiviual_asset_container_layout_4.addWidget(ag.label_8)
        ag.my_id = QtWidgets.QLabel(ag.assign_asset_item)
        ag.my_id.setMinimumSize(QtCore.QSize(100, 0))
        ag.my_id.setMaximumSize(QtCore.QSize(200, 16777215))
        ag.my_id.setObjectName("my_id")
        ag.indiviual_asset_container_layout_4.addWidget(ag.my_id)

        ag.my_selected = QtWidgets.QCheckBox(ag.assign_asset_item)
        ag.my_selected.setObjectName("my_selected")
        ag.indiviual_asset_container_layout_4.addWidget(ag.my_selected)

        ag.label_9 = QtWidgets.QLabel(ag.assign_asset_item)
        ag.label_9.setObjectName("label_9")
        ag.indiviual_asset_container_layout_4.addWidget(ag.label_9)
        ag.my_group = QtWidgets.QComboBox(ag.assign_asset_item)
        ag.my_group.setMaximumSize(QtCore.QSize(100, 16777215))
        ag.my_group.setObjectName("my_group")
        ag.indiviual_asset_container_layout_4.addWidget(ag.my_group)
        spacerItem3 = QtWidgets.QSpacerItem(
            40,
            20,
            QtWidgets.QSizePolicy.Expanding,
            QtWidgets.QSizePolicy.Minimum)
        ag.indiviual_asset_container_layout_4.addItem(spacerItem3)
        self.ui.assign_asset_item_parent_layout.addWidget(ag.assign_asset_item)

        # set text
        _translate = QtCore.QCoreApplication.translate

        ag.label_8.setText(_translate("projectDataWidget", "ID: "))
        ag.my_id.setText(id_)
        ag.label_9.setText(_translate("projectDataWidget", "Group"))

        # connect signal
        ag.my_selected.stateChanged.connect(self.myselectionchanged)
        ag.my_selected.stateChanged.connect(ag._selected_change_color)

        # add this to the record.
        # 1. Add _id to aq
        # 2. then add aq to the record
        ag.id_ = id_
        self.add_plot_item_to_record(id_, ag)

    def _getgroupname(self, i):
        return "G_%02d" % i

    def add_assetgroup(self, i, values=None):
        """values will be used as (A0, N0, age)"""

        ag = PropertyGroupGUI(frame=QFrame())
        ag.container_layout = QtWidgets.QHBoxLayout()
        ag.container_layout.setObjectName("assetgroup_container_layout")
        ag.no_label = QtWidgets.QLabel(self.ui.groupBox)
        ag.no_label.setObjectName("assetgroup_no_label")
        ag.container_layout.addWidget(ag.no_label)
        ag.A_label = QtWidgets.QLabel(self.ui.groupBox)
        ag.A_label.setObjectName("assetgroup_A_label")
        ag.container_layout.addWidget(ag.A_label)
        ag.A = QtWidgets.QLineEdit(self.ui.groupBox)
        ag.A.setMaximumSize(QtCore.QSize(50, 16777215))
        ag.A.setInputMask("")
        ag.A.setObjectName("assetgroup_A")
        ag.container_layout.addWidget(ag.A)
        ag.N0_label = QtWidgets.QLabel(self.ui.groupBox)
        ag.N0_label.setObjectName("assetgroup_N0_label")
        ag.container_layout.addWidget(ag.N0_label)
        ag.N0 = QtWidgets.QLineEdit(self.ui.groupBox)
        ag.N0.setMaximumSize(QtCore.QSize(50, 16777215))
        ag.N0.setInputMask("")
        ag.N0.setObjectName("assetgroup_N0")
        ag.container_layout.addWidget(ag.N0)
        ag.age_label = QtWidgets.QLabel(self.ui.groupBox)
        ag.age_label.setObjectName("assetgroup_age_label")
        ag.container_layout.addWidget(ag.age_label)
        ag.age = QtWidgets.QSpinBox(self.ui.groupBox)
        ag.age.setMaximum(999)
        ag.age.setObjectName("assetgroup_age")
        ag.container_layout.addWidget(ag.age)
        ag.spacer = QtWidgets.QSpacerItem(
            40,
            20,
            QtWidgets.QSizePolicy.Expanding,
            QtWidgets.QSizePolicy.Minimum)
        ag.container_layout.addItem(ag.spacer)

        ag.frame.setLayout(ag.container_layout)
        self.ui.assetgroup_container_parent_layout.addWidget(ag.frame)

        _translate = QtCore.QCoreApplication.translate

        ag.no_label.setText(_translate("projectDataWidget", self._getgroupname(i)))
        ag.A_label.setText(_translate("projectDataWidget", "A"))
        ag.N0_label.setText(_translate("projectDataWidget", "N0"))
        ag.age_label.setText(_translate("projectDataWidget", "Age"))

        # set defaults
        if(values):
            try:
                ag.A.setText(str(values[0]))
                ag.N0.setText(str(values[1]))
                ag.age.setValue(int(values[2]))
            except Exception as e:
                logger = logging.getLogger()
                logger.exception("Error trying to set values with %s (Exception: %s)" % (values, e))
                values = None
        if(not values):
            ag.A.setText(str(c.DEFAULT_A))
            ag.N0.setText(str(c.DEFAULT_N0))
            ag.age.setValue(int(c.DEFAULT_age))

        # Add validators

        ag.valNumber = QtGui.QDoubleValidator()
        ag.A.setValidator(ag.valNumber)
        ag.N0.setValidator(ag.valNumber)
        # ag.valInt=QtGui.QIntValidator()
        # ag.age.setValidator(ag.valInt)

        #
        self.assetgrouplist.append(ag)
        ag.A.textChanged.connect(self._validate_property_groups)
        ag.N0.textChanged.connect(self._validate_property_groups)
        ag.age.valueChanged.connect(self._validate_property_groups)

    def _validate_property_groups(self, item=None):
        logger = logging.getLogger()
        logger.info("Validating property groups...")
        for group in self.assetgrouplist:
            try:
                float(group.A.text())
            except:
                group.A.setText(str(c.DEFAULT_A))
            try:
                float(group.N0.text())
            except:
                group.N0.setText(str(c.DEFAULT_N0))
            try:
                int(group.age.text())
            except:
                group.age.setValue(group.age.value())

    def get_active_groups(self):
        return [x for x in self.assetgrouplist if x.active]

    def closeEvent(self, evnt):
        evnt.ignore()
        self.setWindowState(QtCore.Qt.WindowMinimized)

    def keyPressEvent(self, e):
        if (e.key() != QtCore.Qt.Key_Escape):
            super(DataWindow, self).keyPressEvent(e)
        else:
            pass


class CurveDialogWithClosable(CurveDialog):

    """The mother dialog from which all the graph windows inherit from
       The constructor can send 'options' keyward argument containing a dict. Following entries are
       possible
                 title=None,
                 xlabel=None, ylabel=None, xunit=None, yunit=None,
                 section="plot", show_itemlist=False, gridparam=None,
                 curve_antialiasing=None


    """

    def __init__(self, *args, **kwargs):
        kwargs_ = dict(kwargs)
        del kwargs_["mainwindow"]
        super(CurveDialogWithClosable, self).__init__(*args, **kwargs_)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        self._can_be_closed = True
        self.get_plot().set_antialiasing(True)
        self.add_tools()
        self.selected_holder = kwargs['mainwindow'].selected_holder
        self.enable_selection_update_signals()
        self.get_plot().SIG_ITEM_REMOVED.connect(self.__item_removed)
        self.myplotitems = {}

    def enable_selection_update_signals(self, set=True):
        if(set):
            self.get_plot().SIG_ITEM_SELECTION_CHANGED.connect(self.selected_holder)
            self.get_plot().SIG_ITEM_SELECTION_CHANGED.connect(self.select_siblings)
        else:
            self.get_plot().SIG_ITEM_SELECTION_CHANGED.disconnect()
            # self.get_plot().SIG_ITEM_SELECTION_CHANGED.connect(self.select_siblings)

    def select_siblings(self, widget):
        self.enable_selection_update_signals(False)  # temporariliy disable the signalling
        sel = [x for x in self.get_plot().get_selected_items() if hasattr(x, "id_")]
        items = [x for x in self.get_plot().get_items() if hasattr(x, "id_")]
        for item in sel:
            [self.get_plot().select_item(x) for x in items if x.id_ == item.id_]
        self.enable_selection_update_signals(True)  # now enable signalling

    def set_all_private(self):
        """" Set all current items in the plot private"""
        [x.set_private(True) for x in self.get_plot().get_items()]

    def set_axes_limits(self, axes_limits=None):
        """Sets axes limits axes_limits should be a list with four float values [x0,x1,y0,y1] """
        self.get_plot().PREFERRED_AXES_LIMITS = axes_limits
        # now autoscale
        self.get_plot().do_autoscale()

    def add_tools(self):
        """adds the custom tools necessary"""
        self.add_tool(ResetZoomTool)

    def setClosable(self, closable=True):
        self._can_be_closed = closable

    def closeEvent(self, evnt):
        if self._can_be_closed:
            super(CurveDialogWithClosable, self).closeEvent(evnt)

        else:
            evnt.ignore()
            self.setWindowState(QtCore.Qt.WindowMinimized)

    def keyPressEvent(self, e):
        if (e.key() != QtCore.Qt.Key_Escape):
            super(CurveDialogWithClosable, self).keyPressEvent(e)
        else:
            pass

    def plot_item(self, id_, data, title="Point", icon="pipe.png"):
        raise NotImplemented

    def add_plot_item_to_record(self, id_, item):
        """All the plot items register here by calling this method. See also: remove_plot_item_from_record"""
        # TODO : DataWindow currently copies this function
        # need to implement multiple inheritance and make DRY
        self.myplotitems[id_] = item

    def remove_plot_item_from_record(self, id_):
        """When removing a plot item it should be notified to this function. See also: add_plot_item_to_record """
        # TODO : DataWindow currently copies this function
        # need to implement multiple inheritance and make DRY
        del self.myplotitems[id_]

    def __item_removed(self, goner):
        tmplist = dict(self.myplotitems)
        for id_, item in tmplist.items():
            if goner in item:
                # first remove related items.
                others = [x for x in item if x != goner]
                for i in others:
                    try:
                        self.get_plot().del_item(i)
                    except:
                        pass
                try:
                    self.remove_plot_item_from_record(id_)
                except:
                    pass


class RiskMatrix(CurveDialogWithClosable):
    SCALE = 10.

    def __init__(self, name="Risk Matrix", mainwindow=None, parent=None,
                 units=units["EURO"], options={}, axes_limits=[0, 15000, 0, 100]):
        if("xlabel" not in options):
            options['xlabel'] = "Consequence (%s)" % (units)
        if("ylabel" not in options):
            options['ylabel'] = "Proabability(-)"
        if("gridparam" not in options):
            options['gridparam'] = make.gridparam()

        super(RiskMatrix, self).__init__(edit=False,
                                         icon="risk.svg",
                                         toolbar=True,
                                         options=options,
                                         parent=parent,
                                         panels=None,
                                         wintitle=name,
                                         mainwindow=mainwindow)
        self.setClosable(False)
        self.set_axes_limits(axes_limits)

        l = make.legend("TR")
        self.get_plot().add_item(l)
        self.set_all_private()

    def set_axes_limits(self, axes_limits):
        _axes_limits = axes_limits[0], axes_limits[1] * 1.1, axes_limits[2], axes_limits[3] * 1.1
        super(RiskMatrix, self).set_axes_limits(_axes_limits)

    def get_ellipse_xaxis(self, consequence, probability):
        l = self.get_plot().PREFERRED_AXES_LIMITS
        SCALE = self.get_scale(consequence, probability, l)
        return consequence - SCALE, probability + SCALE,\
            consequence + SCALE, probability - SCALE

    def get_scale(self, consequence, probability, l):
        SCALE = self.SCALE * math.pow(consequence * probability, .25) / math.pow((l[1] * l[3]), .25)
        return SCALE

    def set_proper_axis_limits(self, data):
        a = array(data).T
        min_x, min_y = min(a, axis=0)
        max_x, max_y = max(a, axis=0)
        _axes_limits = [min_x, max_x, min_y, max_y]
        self.set_axes_limits(_axes_limits)

    def plot_links(self, links):
        if (not links):
            return
        if (not (hasattr(links[0], "cons") and hasattr(links[0], "prob"))):
            logger = logging.getLogger()
            logger.info("The link does not have cons, prob attributes. Can not plot risk.")
            return
        adfs = [x.cons for x in links]
        prob = [x.prob for x in links]
        # first compute bounding box
        self.set_proper_axis_limits([adfs, prob])
        for link in links:
            self.plot_item(id_=link.id, data=[link.cons, link.prob], title="Point", icon="pipe.png")

    def plot_item(self, id_, data, title="Point", icon="pipe.png"):
        global STYLE

        consequence, probability = data

        ci = make.ellipse(*self.get_ellipse_xaxis(consequence, probability),
                          title=title)
        ci.shapeparam._DataSet__icon = u.get_icon('Risk')
        ci.shapeparam._DataSet__title = title
        param = ci.shapeparam
        param.fill.color = QColor('red')
        param.sel_fill.color = QColor('purple')
        param.sel_fill.alpha = .7
        param.sel_symbol.Marker = "NoSymbol"
        param.sel_symbol.Color = QColor('red')
        update_style_attr('-r', param)
        param.update_shape(ci)
        ci.id_ = id_  # add the id to the item before plotting.
        self.get_plot().add_item(ci)
        # now add a label with link id
        la = make.label(id_, ci.get_center(), (0, 0), "C")
        la.id_ = id_  # add the id to the item before plotting.
        self.get_plot().add_item(la)
        la.set_private(False)
        self.add_plot_item_to_record(id_, [ci, la])


class NetworkMap(CurveDialogWithClosable):

    def __init__(self, name="Network Map", mainwindow=None,
                 nodes=None, links=None, parent=None, options={}):
        if("xlabel" not in options):
            options['xlabel'] = "X (distance units)"
        if("ylabel" not in options):
            options['ylabel'] = "Y (distance units)"

        gridparam = make.gridparam()

        super(NetworkMap, self).__init__(edit=False,
                                         icon="network.svg",
                                         toolbar=True,
                                         options=dict(gridparam=gridparam),
                                         parent=parent,
                                         wintitle=name,
                                         panels=None,
                                         mainwindow=mainwindow)
        self.setClosable(False)

        # legend = make.legend("TR")
        # self.get_plot().add_item(legend)
        self.set_all_private()
        self.draw_network(nodes, links)

    def draw_network(self, nodes, links):
        logger = logging.getLogger()
        if(nodes):
            logger.info("Drawing nodes")
            self.draw_nodes(nodes)
        # we don't want users to select grid, or nodes and they should not appear in the item list.
        # So lock'em up.
        self.set_all_private()

        if(links):
            logger.info("Drawing links")
            self.draw_links(links)
        self.get_plot().do_autoscale(replot=True)

    def interp_curve(self, x, y):
        # how many points in the line (say max is 5)
        DELTA = .01
        t = arange(len(x))
        t_ = arange(0, len(x) - 1 + DELTA, DELTA)
        x_ = interp(t_, t, x)
        y_ = interp(t_, t, y)

        return x_, y_

    def draw_links(self, links):
        for link in links:
            pts = [(link.start.x, link.start.y)] + link.vertices + [(link.end.x, link.end.y)]
            title = u.get_title(link)
            icon = u.get_icon(link)
            id_ = link.id
            self.plot_item(id_, pts, title, icon)

    def plot_item(self, id_, data, title, icon="pipe.png"):
        x = [n[0] for n in data]
        y = [n[1] for n in data]
        x_, y_ = self.interp_curve(x, y)
        cu = make.curve(x_, y_, title=title)
        cu.curveparam._DataSet__icon = icon
        cu.curveparam._DataSet__title = title
        cu.id_ = id_  # add the ide to the item before plotting.
        self.get_plot().add_item(cu)

        # create a label for the node and add it to the plot
        l = int(len(x_) / 2.0)
        la = make.label(id_, (x_[l], y_[l]), (0, 0), "C")
        la.id_ = id_
        la.set_private(True)
        self.get_plot().add_item(la)
        la.set_private(True)

        self.add_plot_item_to_record(id_, [cu, la])

    def draw_nodes(self, nodes):

        for node in nodes:
            cu = make.curve([node.x, node.x], [node.y, node.y],
                            # ^ this is a hack. gwiqwt curve has problems when constructed with single coordinae
                            title=u.get_title(node), marker="Ellipse", curvestyle="NoCurve")
            cu.set_selectable(False)
            cu.set_private(True)
            # pt=make.ellipse(node.x-.1,node.y-.1,node.x+.1,node.y+.1)
            # pt=PointShape(x=node.x,y=node.y, color="g")
            cu.curveparam._DataSet__icon = u.get_icon(node)
            cu.curveparam._DataSet__title = u.get_title(node)
            self.get_plot().add_item(cu)

            # create a label for the node and add it to the plot
            la = make.label(node.id, (node.x, node.y), (0, 0), "TL")
            la.set_private(True)
            self.get_plot().add_item(la)


class optimalTimeGraph(CurveDialogWithClosable):

    def __init__(self, name="Whole life cost", mainwindow=None, year=None,
                 damagecost=None, renewalcost=None, units=units["EURO"],
                 parent=None, options={}):
        self.mainwindow = mainwindow
        if("xlabel" not in options):
            options['xlabel'] = "Time(years)"
        if("ylabel" not in options):
            options['ylabel'] = "Cost (%s)" % (units)

        self.curvesets = []

        super(optimalTimeGraph, self).__init__(edit=False,
                                               icon="wlc.svg",
                                               toolbar=True,
                                               options=options,
                                               parent=parent,
                                               panels=None,
                                               wintitle=name,
                                               mainwindow=mainwindow)
        if (isinstance(self.mainwindow, MainWindow)):
            self.mainwindow.optimaltimegraphs[id(self)] = self
        legend = make.legend("TR")
        self.get_plot().add_item(legend)
        if(year is None or damagecost is None or renewalcost is None):
            pass
        else:
            self.plotCurveSet(name, year, damagecost, renewalcost)

    def closeEvent(self, evnt):
        if (not isinstance(self.mainwindow, MainWindow)):
            _can_be_closed = True
        elif (len(self.mainwindow.optimaltimegraphs) > 1):
            _can_be_closed = True
            del(self.mainwindow.optimaltimegraphs[id(self)])
        else:
            _can_be_closed = False

        if _can_be_closed:
            super(optimalTimeGraph, self).closeEvent(evnt)
        else:
            evnt.ignore()
            self.setWindowState(QtCore.Qt.WindowMinimized)

    def plot_item(self, id_, data, title, icon="pipe.png"):
        year, damagecost, renewalcost = data
        self.add_plot_item_to_record(id_, self.plotCurveSet(title, year, damagecost, renewalcost))

    def plotCurveSet(self, id_, year, damagecost, renewalcost):
        c = curve_colors[len(self.curvesets) % len(curve_colors)]
        dc = make.curve(
            year, damagecost, title="Damage Cost", color=c, linestyle="DashLine",
            linewidth=3, marker=None,
            markersize=None,
            markerfacecolor=None,
            markeredgecolor=None, shade=None,
            curvestyle=None, baseline=None,
            xaxis="bottom", yaxis="left")
        dc.id_ = id_  # add the ide to the item before plotting.
        self.get_plot().add_item(dc)
        rc = make.curve(
            year, renewalcost, title="Renewal Cost", color=c, linestyle="DotLine",
            linewidth=3, marker=None,
            markersize=None,
            markerfacecolor=None,
            markeredgecolor=None, shade=None,
            curvestyle=None, baseline=None,
            xaxis="bottom", yaxis="left")
        rc.id_ = id_  # add the ide to the item before plotting.
        self.get_plot().add_item(rc)
        tc = make.curve(
            year, array(damagecost) + array(renewalcost), title="Total Cost", color=c, linestyle=None,
            linewidth=5, marker=None,
            markersize=None,
            markerfacecolor=None,
            markeredgecolor=None, shade=None,
            curvestyle="Lines", baseline=None,
            xaxis="bottom", yaxis="left")
        tc.id_ = id_  # add the ide to the item before plotting.
        self.get_plot().add_item(tc)
        self.curvesets.append([id_, dc, tc, rc])
        return [dc, tc, rc]


class MainWindow(QMainWindow):

    """The maion 'container' of the application. This is a multi-document interface where all other
    windows live in."""

    class MenuItems:
        pass
    menuitems = MenuItems
    menuitems.file = "&File"
    menuitems.view = "&View"
    menuitems.new_wlc = "New &WLC window"
    menuitems.cascade = "&Cascade"
    menuitems.tiled = "&Tiled"
    menuitems.show_log = "Show &Log"
    menuitems.new_project = "&New Project"
    menuitems.open_project = "&Open project"
    menuitems.save_project_as = "Save Project &As"
    menuitems.save_project = "&Save Project"

    menuitems.close_project = "&Close Project"

    update_selected_items = True
    LOGSTARTMESSAGE = "Logging started"

    def __init__(self, parent=None):

        super(MainWindow, self).__init__(parent)
        self._setup_logging()
        self.LASTPROJECT = None
        self.EPANETLOC = None
        self.projectgui = rrpam_wds.gui.subdialogs.ProjectGUI(self)
        self.mdi = QMdiArea()
        self.arrange_properties_panel()
        self.setMenu()
        self._standard_windows()
        self.connect_project_manager()
        self._manage_window_settings()

    def arrange_properties_panel(self):
        self.qs = QSplitter(self)
        self.frame = QFrame(parent=self)
        layout = QVBoxLayout()
        layout.addWidget(self.projectgui.projectproperties)
        layout.insertStretch(1)
        self.frame.setLayout(layout)
        self.qs.addWidget(self.frame)
        for x in self.projectgui.projectproperties.findChildren(QSlider):
            x.setMinimumWidth(100)

        self.qs.addWidget(self.mdi)
        self.setCentralWidget(self.qs)

    def _manage_window_settings(self, save=False):
        """ if (save=False) At application initialization, will set the application GUI geometry and components
        from  values saved at the end of the previous session.

        Otherwise (save=True) it will
        """
        QApplication.setOrganizationName("AsselaPathirana")
        QApplication.setOrganizationDomain("assela.pathirana.net")
        QApplication.setApplicationName("RRPAMWDS")
        settings = QtCore.QSettings()

        if(save):
            settings.beginGroup("MainWindow")
            settings.setValue("size", self.size())
            settings.setValue("pos", self.pos())
            settings.endGroup()
            settings.beginGroup("last_project")
            settings.setValue("LASTPROJECT", self.LASTPROJECT)
            settings.setValue("EPANETLOC", self.EPANETLOC)
            settings.endGroup()
        else:

            settings.beginGroup("MainWindow")
            self.resize(settings.value("size", QtCore.QSize(400, 400), type=QtCore.QSize))
            self.move(settings.value("pos", QtCore.QPoint(200, 200), type=QtCore.QPoint))
            settings.endGroup()
            settings.beginGroup("last_project")
            self.LASTPROJECT = settings.value("LASTPROJECT", None, type=str)
            self.EPANETLOC = settings.value("EPANETLOC", None, type=str)
            settings.endGroup()

    def closeEvent(self, event):
        self._manage_window_settings(save=True)
        event.accept()

    def _setup_logging(self):
        setup_logging()
        logger = logging.getLogger()
        handler = [x for x in logger.handlers if isinstance(x, EmittingLogger)][0]
        self.logdialog = LogDialog(parent=self)
        handler.logsender.logsender_signal.connect(self.logdialog.reciever)
        logger.info(self.LOGSTARTMESSAGE)

    def hide_log_window(self):
        self.logdialog.setVisible(False)
        logmdi = [x for x in self.mdi.subWindowList() if isinstance(x.widget(), LogDialog)][0]
        logmdi.setVisible(False)

    def show_logwindow(self):
        if(not any([x for x in self.mdi.subWindowList() if isinstance(x.widget(), LogDialog)])):
            self.addSubWindow(self.logdialog)
        self.logdialog.setVisible(True)

    def connect_project_manager(self):
        self.pm = PM(self.projectgui.projectproperties.dataset)
        self.projectgui._new_project_signal.connect(self.pm.new_project)
        self.pm.heres_a_project_signal.connect(self.take_up_results)

    def _standard_windows(self):
        self.add_datawindow()
        self.add_networkmap()
        self.add_riskmatrix()
        self.optimaltimegraphs = {}
        self.add_optimaltimegraph()

    def selected_holder(self, widget):
        """ When mocking remember do not patch slots. This is a slot. So, instead patch the function this calls below. """
        logger = logging.getLogger()
        logger.info("Got message of change from: %s" % widget)
        if(self.update_selected_items):
            self.update_all_plots_with_selection(widget)

    def update_all_plots_with_selection(self, widget):
        logger = logging.getLogger()
        logger.info("selection changed!")
        try:
            # firt get all subplots
            subplots = [x.get_plot() for x in self.optimaltimegraphs.values()]
            subplots.append(self.riskmatrix.get_plot())
            subplots.append(self.networkmap.get_plot())
            subplots.append(self.datawindow.get_plot())
            # OK, now remove the plot represented by the argument 'widget'
            subplots = filter(lambda a: a != widget, subplots)
            # now select the selections of 'widget' in them.
            selected_ids = [x.id_ for x in widget.get_selected_items()]
            for p in subplots:
                # first switch off responding to selections
                self.update_selected_items = False
                # find corressponding items
                targets = [x for x in p.get_items() if getattr(x, 'id_', None) in selected_ids]
                # now update
                p.select_some_items(targets)
                # don't forget to reset

        except Exception as e:
            logger = logging.getLogger()
            logger.exception("non selectable item! (%s)" % e)
        self.update_selected_items = True

    def add_optimaltimegraph(self):
        wlc = optimalTimeGraph(mainwindow=self)
        self.mdi.addSubWindow(wlc)
        wlc.show()

    def add_datawindow(self):
        if(not any([x for x in self.mdi.subWindowList() if isinstance(x.widget(), DataWindow)])):
            self.datawindow = DataWindow(mainwindow=self, parent=self.mdi)
            self.mdi.addSubWindow(self.datawindow)
            self.datawindow.show()

    def add_riskmatrix(self):
        if(not any([x for x in self.mdi.subWindowList() if isinstance(x.widget(), RiskMatrix)])):
            self.riskmatrix = RiskMatrix(mainwindow=self)
            self.mdi.addSubWindow(self.riskmatrix)
            self.riskmatrix.show()

    def add_networkmap(self):
        if(not any([x for x in self.mdi.subWindowList() if isinstance(x.widget(), NetworkMap)])):
            self.networkmap = NetworkMap("Network Map", mainwindow=self)
            self.mdi.addSubWindow(self.networkmap)
            self.networkmap.show()

    def setMenu(self):
        bar = self.menuBar()
        bar.setNativeMenuBar(False)  # disable different treatment in Mac OS
        file = bar.addMenu(self.menuitems.file)
        file.addAction(self.menuitems.new_project)
        file.addAction(self.menuitems.save_project)
        file.addAction(self.menuitems.save_project_as)
        file.addAction(self.menuitems.open_project)
        file.addAction(self.menuitems.new_wlc)
        file.addAction(self.menuitems.show_log)
        file.addAction(self.menuitems.close_project)
        file.triggered[QAction].connect(self.windowaction)
        file2 = bar.addMenu(self.menuitems.view)
        file2.addAction(self.menuitems.cascade)
        file2.addAction(self.menuitems.tiled)
        file2.triggered[QAction].connect(self.windowaction)

    def windowaction(self, q):
        logger = logging.getLogger()
        logger.info("Menu: %s" % q.text())

        if q.text() == self.menuitems.new_wlc:
            self.add_optimaltimegraph()

        if q.text() == self.menuitems.cascade:
            self.mdi.cascadeSubWindows()

        if q.text() == self.menuitems.tiled:
            self.mdi.tileSubWindows()

        if q.text() == self.menuitems.show_log:
            self.show_logwindow()

        if q.text() == self.menuitems.new_project:
            self._new_project()

        if q.text() == self.menuitems.open_project:
            self._open_project()

        if q.text() == self.menuitems.save_project:
            self.projectgui.save_project()

        if q.text() == self.menuitems.save_project_as:
            self.projectgui.save_project_as()

        if q.text() == self.menuitems.close_project:
            self.projectgui.close_project()

    def _new_project(self):
        self.projectgui.new_project()

    def _open_project(self):
        """Opening a project"""
        self.projectgui.open_project()

    @pyqtSlot(object)
    def take_up_results(self, results):
        """Will display the items represented in the project."""

        logger = logging.getLogger()
        logger.info("I got it!")
        # first update this in project properties
        self.projectgui.projectproperties.dataset.set_network(results)
        self._display_project(results)

    def _display_project(self, results=None):
        if (not results):
            results = self.projectgui.projectproperties.dataset.get_network()
        nodes = getattr(results, "nodes", None)
        links = getattr(results, "links", None)

        # id_  =project.id
        self.networkmap.draw_network(nodes, links)
        self.datawindow.draw_network(links)
        self.riskmatrix.plot_links(links)

    def addSubWindow(self, *args, **kwargs):
        self.mdi.addSubWindow(*args, **kwargs)

    def new_window(self, closable=True, mainwindow=None):
        win = CurveDialogWithClosable(
            edit=False, toolbar=True, wintitle="CurveDialog test", mainwindow=mainwindow,
            options=dict(title="Title", xlabel="xlabel", ylabel="ylabel"))
        win.setClosable(closable)
        self.plot_some_junk(win)

        # win.setWindowTitle("subwindow" + str(MainWindow.count))
        self.mdi.addSubWindow(win)
        win.show()
        return win

    def new_matplotlib_window(self, closable=True):
        win = MatplotlibDialog()
        # win.setClosable(closable)
        # self.plot_some_junk(win)

        # win.setWindowTitle("subwindow" + str(MainWindow.count))
        self.mdi.addSubWindow(win)
        win.show()

    def plot_some_junk(self, win):
        plot = win.get_plot()
        x2 = linspace(-10, 10, 20)
        y2 = sin(sin(sin(x2)))
        curve2 = make.curve(x2, y2, color="g", curvestyle="Sticks")
        curve2.setTitle("toto")
        plot.add_item(curve2)

        # if q.text() == "graph"


class MatplotlibDialog(QDialog):

    def __init__(self):
        QDialog.__init__(self)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        self.setWindowTitle("application main window")

        # self.main_widget = QWidget(self)

        l = QVBoxLayout(self)
        sc = MyStaticMplCanvas(self, width=5, height=2, dpi=100)
        navi_toolbar = NavigationToolbar(sc, self)
        dc = MyDynamicMplCanvas(self, width=5, height=2, dpi=100)
        navi_toolbar2 = NavigationToolbar(dc, self)
        l.addWidget(sc)
        l.addWidget(navi_toolbar)
        l.addWidget(dc)
        l.addWidget(navi_toolbar2)

        # self.main_widget.setFocus()
        self.resize(self.sizeHint())
        # self.setCentralWidget(self.main_widget)
        # self.statusBar().showMessage("All hail matplotlib!", 2000)


class MyMplCanvas(FigureCanvas):

    """Ultimately, this is a QWidget (as well as a FigureCanvasAgg, etc.)."""

    def __init__(self, parent=None, width=5, height=4, dpi=100):
        fig = Figure(figsize=(width, height), dpi=dpi)
        self.axes = fig.add_subplot(111)
        # We want the axes cleared every time plot() is called
        self.axes.hold(False)

        self.compute_initial_figure()
        FigureCanvas.__init__(self, fig)
        self.setParent(parent)

        FigureCanvas.setSizePolicy(self,
                                   QSizePolicy.Expanding,
                                   QSizePolicy.Expanding)
        FigureCanvas.updateGeometry(self)

    def compute_initial_figure(self):
        pass


class MyStaticMplCanvas(MyMplCanvas):

    """Simple canvas with a sine plot."""

    def compute_initial_figure(self):
        t = arange(0.0, 3.0, 0.01)
        s = sin(2 * pi * t)
        self.axes.plot(t, s)


class MyDynamicMplCanvas(MyMplCanvas):

    """A canvas that updates itself every second with a new plot."""

    def __init__(self, *args, **kwargs):
        MyMplCanvas.__init__(self, *args, **kwargs)
        timer = QtCore.QTimer(self)
        timer.timeout.connect(self.update_figure)
        timer.start(1000)

    def compute_initial_figure(self):
        self.axes.plot([0, 1, 2, 3], [1, 2, 0, 4], 'r')

    def update_figure(self):
        # Build a list of 4 random integers between 0 and 10 (both inclusive)
        l = [random.randint(0, 10) for i in range(4)]

        self.axes.plot([0, 1, 2, 3], l, 'r')
        self.draw()


def main():
    app = QApplication(sys.argv)
    ex = MainWindow()
    mpl = MatplotlibDialog()
    ex.addSubWindow(mpl)
    ex.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
