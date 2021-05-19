# -*- coding: utf-8 -*-

import os
import json
import shutil

try:
    from PySide2 import QtCore
    from PySide2 import QtGui
    from PySide2 import QtWidgets
except:
    from PyQt5.QtCore import pyqtSlot as Slot
    from PyQt5 import QtCore
    from PyQt5 import QtGui
    from PyQt5 import QtWidgets

from SyncthingAPI import SyncthingAPI
from FileSystem import FileSystem
from TreeModel import TreeModel
import ItemProperty as iprop

import logging
logger = logging.getLogger("PySel.MainWindow")

# use helloword from https://evileg.com/ru/post/63/
class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        QtWidgets.QMainWindow.__init__(self)
        self._qtver = \
                (int(QtCore.qVersion().split('.')[0]) << 16) + \
                (int(QtCore.qVersion().split('.')[1]) << 8) + \
                int(QtCore.qVersion().split('.')[2])
        logger.debug("Runtime Qt version {0} ({1})".format(QtCore.qVersion(), self._qtver))
        self.setMinimumSize(QtCore.QSize(150, 250))
        self.setWindowTitle("Syncthing PySelective")
        self.setWindowIcon(QtGui.QIcon('icons/syncthing_pysel.png'))
        central_widget = QtWidgets.QWidget(self)
        self.cw = central_widget
        self.setCentralWidget(central_widget)

        grid_layout = QtWidgets.QGridLayout(central_widget)

        title = QtWidgets.QLabel("Choise the folder:", self)
        title.setAlignment(QtCore.Qt.AlignCenter)
        grid_layout.addWidget(title, 0, 0, 1, 2)

        self.cbfolder = QtWidgets.QComboBox(central_widget)
        self.cbfolder.currentIndexChanged[int].connect(self.folderSelected)
        grid_layout.addWidget( self.cbfolder, 1, 0, 1, 2)

        self.tv = QtWidgets.QTreeView(central_widget)
        grid_layout.addWidget( self.tv, 2, 0, 1, 2)
        self.tm = TreeModel(parent=self.tv)
        self.tv.setModel(self.tm)
        self.tv.header().setSectionsMovable(True)
        if self._qtver >= 0x050B00: # >= 5.11
            self.tv.header().setFirstSectionMovable(True)
        self.tv.expanded.connect(self.updateSectionInfo)

        # create context menu
        self.cm = QtWidgets.QMenu(self)
        infoAct = self.cm.addAction("Info")
        infoAct.triggered.connect(self.actInfo)
        self.rmAct = self.cm.addAction("Remove")
        self.rmAct.setEnabled(False)
        self.rmAct.triggered.connect(self.actRemove)

        pb = QtWidgets.QPushButton("Get file tree", central_widget)
        pb.clicked.connect(self.btGetClicked)
        grid_layout.addWidget( pb, 3, 0, 1, 2)

        pb = QtWidgets.QPushButton("Submit changes", central_widget)
        pb.clicked.connect(self.btSubmitClicked)
        grid_layout.addWidget( pb, 4, 0, 1, 2)

        lapi = QtWidgets.QLabel("API Key:", self)
        grid_layout.addWidget(lapi, 5, 0, 1, 1)
        self.leKey = QtWidgets.QLineEdit(central_widget)
        self.leKey.editingFinished.connect(self.leSaveKeyAPI)
        if self._qtver >= 0x050C00: # >= 5.12
            self.leKey.inputRejected.connect(self.leRestoreKeyAPI)
        grid_layout.addWidget( self.leKey, 5, 1, 1, 1)

        labelver = QtWidgets.QLabel("Syncthing version:", self)
        grid_layout.addWidget(labelver, 6, 0, 1, 1)
        self.lver = QtWidgets.QLabel("None", self)
        grid_layout.addWidget(self.lver, 6, 1, 1, 1)

        #self.te = QtWidgets.QTextEdit(central_widget)
        #grid_layout.addWidget( self.te, 5, 0)

        #exit_action = QtWidgets.QAction("&Exit", self)
        #exit_action.setShortcut('Ctrl+Q')
        #exit_action.triggered.connect(QtWidgets.qApp.quit)
        #file_menu = self.menuBar()
        #file_menu.addAction(exit_action)

        self.currentfid = None
        self.syncapi = SyncthingAPI()
        self.fs = FileSystem()

        self.readSettings()
        settings = QtCore.QSettings("Syncthing-PySelective", "pysel");
        settings.beginGroup("Syncthing");
        self.leKey.setText( settings.value("apikey", "None"))
        settings.endGroup();
        self.syncapi.api_token = self.leKey.text()
        # try set date format
        try:
            self.df = QtCore.Qt.ISODateWithMs
        except AttributeError:
            self.df = QtCore.Qt.ISODate
            logger.warning("Your Qt version is too old, date conversion could be incomplete")

    def extendFileInfo(self, fid, l, path = ''):
        contents = self.syncapi.browseFolderPartial(fid, path, lev=1)
        if path != '' and path[-1] != '/':
            path = path + '/'
        for v in l:
            extd = self.syncapi.getFileInfoExtended( fid, path+v['name'])
            if len(extd) == 0:  # there is no such file in database
                continue
            v['size'] = extd['global']['size']
            v['modified'] = QtCore.QDateTime.fromString( extd['global']['modified'], self.df)
            v['ignored'] = extd['local']['ignored']
            v['invalid'] = extd['local']['invalid']

            if iprop.Type[v['type']] is iprop.Type.DIRECTORY:
                # TODO dict of dicts to avoid for
                for c in contents:
                    if c['name'] == v['name']:
                        if 'children' in c:
                            v['children'] = c['children']
                        else:
                            v['children'] = []

            if iprop.Type[v['type']] is not iprop.Type.DIRECTORY:
                pass
            elif 'partial' in extd['local']:
                v['partial'] = extd['local']['partial']
            else: #do not believe 'ignore', check content
                selcnt = 0
                for v2 in v['children']:
                    if self.syncapi.getFileInfoExtended( \
                            fid, path+v['name']+'/' + v2['name'])['local']['ignored'] == False:
                        selcnt += 1

                if selcnt == 0:
                    v['partial'] = False
                elif selcnt == len(v['children']):
                    v['ignored'] = False
                    v['partial'] = False
                else:
                    v['ignored'] = False
                    v['partial'] = True


            if not v['ignored'] or ('partial' in v and v['partial']):
                v['syncstate'] = iprop.SyncState.syncing
            else:
                v['syncstate'] = iprop.SyncState.ignored

    def btGetClicked(self):
        self.setCursor(QtCore.Qt.WaitCursor)
        logger.info("Button get clicked")
        self.lver.setText(self.syncapi.getVersion())
        self.syncapi.clearCache()
        d = self.syncapi.getFoldersDict()
        self.foldsdict = d
        self.cbfolder.clear()
        for k in d.keys():
            self.cbfolder.addItem(d[k]['label'], k)
        self.unsetCursor()

    def btSubmitClicked(self):
        self.setCursor(QtCore.Qt.WaitCursor)
        logger.info("Button submit clicked")
        if self.currentfid is not None:
            nl = self.tm.checkedStatePathList() #new list
            pl = self.tm.checkedStatePathList(state = QtCore.Qt.PartiallyChecked)
            cl = self.tm.changedPathList() #changed list
            il = self.syncapi.getIgnoreSelective(self.currentfid) #ignore list
            newignores = self.buildNewIgnoreList(cl, nl, pl, il)
            if QtWidgets.QMessageBox.question( self, "Submit changes", "Are you sure?") == QtWidgets.QMessageBox.Yes:
                logger.info("Changes accepted")
                self.syncapi.setIgnoreSelective(self.currentfid, newignores)
            else:
                logger.info("Changes rejected")
        self.unsetCursor()

    def writeSettings(self):
        settings = QtCore.QSettings("Syncthing-PySelective", "pysel");
        settings.beginGroup("MainWindow");
        settings.setValue("size", self.size());
        settings.setValue("pos", self.pos());
        settings.endGroup();

    def readSettings(self):
        settings = QtCore.QSettings("Syncthing-PySelective", "pysel");
        settings.beginGroup("MainWindow");
        self.resize(settings.value("size", QtCore.QSize(350, 350)));
        self.move(settings.value("pos", QtCore.QPoint(200, 200)));
        settings.endGroup();

    def leSaveKeyAPI(self):
        settings = QtCore.QSettings("Syncthing-PySelective", "pysel");
        settings.beginGroup("Syncthing");
        settings.setValue("apikey", self.leKey.text());
        settings.endGroup();
        self.syncapi.api_token = self.leKey.text()

    def leRestoreKeyAPI(self):
        settings = QtCore.QSettings("Syncthing-PySelective", "pysel");
        settings.beginGroup("Syncthing");
        self.leKey.setText( settings.value("apikey", "None"))
        settings.endGroup();

    def closeEvent(self, event):
        self.writeSettings()
        event.accept()

    def folderSelected(self, index):
        if index < 0: #avoid signal from empty box
            return

        self.setCursor(QtCore.Qt.WaitCursor)
        fid = self.cbfolder.itemData(index)
        self.currentfid = fid
        logger.info("Folder with fid {0} selected".format(fid))
        logger.info("Path is {}".format(self.foldsdict[fid]['path']))
        l = self.syncapi.browseFolderPartial(fid)
        logger.debug("Items: {}".format(l))
        self.extendFileInfo(self.currentfid, l)
        logger.debug("Extended items: {}".format(l))
        self.fs.extendByLocal(l, self.foldsdict[fid]['path'])
        logger.debug("Extended and local items: {}".format(l))
        self.tm = TreeModel(l, self.tv)
        self.tv.setModel(self.tm)
        self.tv.resizeColumnToContents(0)
        self.unsetCursor()

    def updateSectionInfo(self, index):
        self.setCursor(QtCore.Qt.WaitCursor)
        logger.info("Try update section {0}".format(self.tm.data(index, QtCore.Qt.DisplayRole)))
        l = self.tm.rowNamesList(index)
        logger.debug("Items: {}".format(l))
        self.extendFileInfo(self.currentfid, l, self.tm.fullItemName(self.tm.getItem(index)))
        logger.debug("Extended items: {}".format(l))
        self.fs.extendByLocal(l, os.path.join(
            self.foldsdict[self.currentfid]['path'], self.tm.fullItemName(self.tm.getItem(index))
            ))
        logger.debug("Extended and local items: {}".format(l))
        self.tm.updateSubSection(index, l)
        self.unsetCursor()

    def buildNewIgnoreList(self, changedlist, checkedlist, partiallist, ignorelist):
        logger.debug("Changed list:\n{0}".format(changedlist))
        logger.debug("Checked list:\n{0}".format(checkedlist))
        logger.debug("Partially checked list:\n{0}".format(partiallist))
        logger.debug("Initial ignores:\n{0}".format(ignorelist))

        # clean lists
        for v in changedlist:
            # clear exact matching
            if ('!' + v) in ignorelist:
                ignorelist.remove('!' + v)
            # clear ignore (valid for partially synced dirs)
            if (v + '/**') in ignorelist:
                ignorelist.remove(v + '/**')
            # remove subitems if parent is not partially checked
            # add / to be sure that compare with subdirs
            if (v in checkedlist) or (v not in partiallist):
                for i in ignorelist[:]:
                    if (i.startswith(v + '/') and i != v) or i.startswith('!' + v + '/'):
                        ignorelist.remove(i)
                for c in checkedlist[:]:
                    if (c.startswith(v + '/') and c != v) or c.startswith('!' + v + '/'):
                        checkedlist.remove(c)
        logger.debug("Result of clean:\n{0}".format(ignorelist))

        # exclude item from ignore if checked
        for v in changedlist:
            if v in checkedlist:
                ignorelist.insert(0, '!' + v)
        logger.debug("Result of exclude:\n{0}".format(ignorelist))

        # hack to sync parent folder, seems could be skipped for versions above 1.5
        for v in changedlist:
            if v in partiallist:
                ignorelist.append(v + '/**')
                ignorelist.append('!' + v)
        logger.debug("Result of hack:\n{0}".format(ignorelist))

        while ignorelist.count(''):
            ignorelist.remove('')

        logger.debug("Resulted ignores:\n{0}".format(ignorelist))
        return ignorelist

    def contextMenuEvent(self, e):
        logger.debug("Context menu event at position {} with {} selected rows".format(e.pos(), len(self.tv.selectionModel().selectedRows())))
        if len(self.tv.selectionModel().selectedRows()) > 0:
            item = self.tm.getItem(self.tv.selectionModel().currentIndex())
            if item.getSyncState() == iprop.SyncState.newlocal or \
                    item.getSyncState() == iprop.SyncState.conflict or \
                    item.getSyncState() == iprop.SyncState.exists:
                self.rmAct.setEnabled(True)
            else:
                self.rmAct.setEnabled(False)
            self.cm.popup(e.globalPos())

    def actInfo(self):
        'returns file info json string'
        item = self.tm.getItem(self.tv.selectionModel().currentIndex())
        path = self.tm.fullItemName(item)
        d1 = self.syncapi.getFileInfoExtended( self.currentfid, path)
        d2 = item.toDict()
        s1 = json.dumps(d1, indent=4)
        s2 = json.dumps(d2, indent=4)
        msgBox = QtWidgets.QMessageBox()
        msgBox.setWindowTitle("File info")
        msgBox.setText(path)
        msgBox.setInformativeText("Database:\n{}\n\nLocal:\n{}".format(s1, s2))
        msgBox.exec()

    def actRemove(self):
        'remove selected path completely'
        index = self.tv.selectionModel().currentIndex()
        item = self.tm.getItem(index)
        path = self.tm.fullItemName(item)
        path = os.path.join( self.foldsdict[self.currentfid]['path'], path)
        logger.debug("Remove the path {}".format(path))
        try:
            if os.path.isfile(path):
                os.remove(path)
            else:
                shutil.rmtree(path)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Remove path error", "Path: {}\n\nCode:{}".format(path, e))
        self.updateSectionInfo(self.tm.parent(index))
