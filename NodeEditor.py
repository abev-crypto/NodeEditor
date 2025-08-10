from turtle import left
from PySide2 import QtWidgets, QtCore, QtGui
import maya.OpenMayaUI as omui
import maya.cmds as cmds
from shiboken2 import wrapInstance

def get_maya_window():
    ptr = omui.MQtUtil.mainWindow()
    return wrapInstance(int(ptr), QtWidgets.QWidget)

# ===== ポートアイテム =====
class PortItem(QtWidgets.QGraphicsEllipseItem):
    def __init__(self, name, side, radius=14, parent=None):
        super(PortItem, self).__init__(-radius/2, -radius/2, radius, radius, parent)
        self.name = name
        self.side = side

        # 軸判定（最後の文字がX/Y/Z）
        axis = name[-3]  # 例: TranslateX_L → X
        color = self.get_color_for_axis(axis, side)
        self.setBrush(QtGui.QBrush(color))

        self.setFlag(QtWidgets.QGraphicsItem.ItemSendsScenePositionChanges)
        self.setAcceptHoverEvents(True)
        self.connected_lines = []

    def get_color_for_axis(self, axis, side):
        # XYZごとにRGB
        color_map = {
            "X": QtGui.QColor(255, 0, 0),   # 赤
            "Y": QtGui.QColor(0, 255, 0),   # 緑
            "Z": QtGui.QColor(0, 0, 255)    # 青
        }
        base_color = color_map.get(axis, QtGui.QColor(128, 128, 128))

        # 左右で明暗分け
        if side == "R":
            base_color = base_color.lighter(150)
        else:
            base_color = base_color.darker(120)

        return base_color

    def get_attr_name(self):
        attr_name = self.name[:-2]
        base = attr_name[:-1].lower()
        axis = attr_name[-1]
        return base + axis

    def hoverEnterEvent(self, event):
        self.setBrush(QtGui.QBrush(QtCore.Qt.green))
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        axis = self.name[-3]
        color = self.get_color_for_axis(axis, self.side)
        self.setBrush(QtGui.QBrush(color))
        super().hoverLeaveEvent(event)

# ===== ワイヤ =====
class WireLine(QtWidgets.QGraphicsPathItem):
    def __init__(self, start_pos, end_pos, color=QtCore.Qt.green, connection_type="connect", bezier=False):
        super(WireLine, self).__init__()
        self.connection_type = connection_type
        self.bezier = bezier
        self.setPen(QtGui.QPen(color, 2))
        self.start_pos = start_pos
        self.update_path(start_pos, end_pos)
        self.setZValue(-1)
        self.setFlag(QtWidgets.QGraphicsItem.ItemIsSelectable, True)

        self.connected_ports = []

    def update_path(self, start_pos, end_pos):
        self.start_pos = start_pos
        path = QtGui.QPainterPath(start_pos)
        if self.bezier:
            ctrl1 = QtCore.QPointF((start_pos.x() + end_pos.x()) / 2, start_pos.y())
            ctrl2 = QtCore.QPointF((start_pos.x() + end_pos.x()) / 2, end_pos.y())
            path.cubicTo(ctrl1, ctrl2, end_pos)
        else:
            path.lineTo(end_pos)
        self.setPath(path)

    def update_end(self, end_pos):
        self.update_path(self.start_pos, end_pos)

    def paint(self, painter, option, widget=None):
        # 選択時は赤点線
        if self.isSelected():
            pen = QtGui.QPen(QtCore.Qt.red, 2, QtCore.Qt.DashLine)
        else:
            pen = self.pen()
        painter.setPen(pen)
        painter.drawPath(self.path())

    def get_source_port(self):
        return self.connected_ports[0]

    def get_target_port(self):
        return self.connected_ports[1]

# ===== シーン =====
class NodeScene(QtWidgets.QGraphicsScene):
    def __init__(self):
        super(NodeScene, self).__init__()
        self.start_port = None
        self.temp_line = None
        self.wire_items = []

    def mousePressEvent(self, event):
        item = self.itemAt(event.scenePos(), QtGui.QTransform())
        modifiers = event.modifiers()

        # Altクリック → ワイヤ解除
        if modifiers == QtCore.Qt.AltModifier and isinstance(item, PortItem):
            # （既存解除処理そのまま）
            ...

        # Portクリック → ワイヤ接続開始
        if isinstance(item, PortItem):
            self.views()[0].setDragMode(QtWidgets.QGraphicsView.NoDrag)

            # Shift押下なら DrivenKey モード
            if modifiers == QtCore.Qt.ShiftModifier:
                color = QtCore.Qt.blue
                conn_type = "driven"
            else:
                color = QtCore.Qt.green
                conn_type = "connect"

            self.start_port = item
            self.temp_line = WireLine(item.scenePos(), item.scenePos(), color=color, connection_type=conn_type)
            self.addItem(self.temp_line)
        else:
            # Port以外クリックで終了
            if self.temp_line:
                self.removeItem(self.temp_line)
                self.temp_line = None
                self.start_port = None
                self.views()[0].setDragMode(QtWidgets.QGraphicsView.RubberBandDrag)

        super(NodeScene, self).mousePressEvent(event)


    def mouseMoveEvent(self, event):
        if self.temp_line:
            self.temp_line.update_end(event.scenePos())
        super(NodeScene, self).mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.temp_line:
            # ドロップ位置のアイテムを確認
            items_at_pos = self.items(event.scenePos())
            target_port = None
            for i in items_at_pos:
                if isinstance(i, PortItem) and i != self.start_port:
                    target_port = i
                    break

            # Port間接続判定
            if target_port and self.start_port.side != target_port.side:
                source_port = self.start_port if self.start_port.side == "L" else target_port
                target_port = target_port if target_port.side == "R" else self.start_port

                # 右ポートの既存接続を削除して上書き
                if target_port.connected_lines:
                    for old_line in target_port.connected_lines[:]:
                        for port in self.items():
                            if isinstance(port, PortItem) and old_line in port.connected_lines:
                                port.connected_lines.remove(old_line)
                        self.removeItem(old_line)
                    target_port.connected_lines.clear()

                # 接続確定
                self.temp_line.update_path(source_port.scenePos(), target_port.scenePos())
                self.temp_line.connected_ports = [source_port, target_port]
                self.wire_items.append(self.temp_line)
                source_port.connected_lines.append(self.temp_line)
                target_port.connected_lines.append(self.temp_line)
            else:
                # 接続失敗 → 線を削除
                self.removeItem(self.temp_line)

            # 常にモード解除
            self.temp_line = None
            self.start_port = None
            self.views()[0].setDragMode(QtWidgets.QGraphicsView.RubberBandDrag)

        super(NodeScene, self).mouseReleaseEvent(event)


# ===== メインウィンドウ =====
class NodeEditorWindow(QtWidgets.QMainWindow):
    def __init__(self, parent=None):
        super(NodeEditorWindow, self).__init__(parent)
        self.setWindowTitle("TRS Wire Connect UI")
        self.resize(450, 400)

        self.source_node = None
        self.target_node = []

        # Scene & View
        self.scene = NodeScene()
        self.view = QtWidgets.QGraphicsView(self.scene)
        self.view.setRenderHint(QtGui.QPainter.Antialiasing)
        self.view.setDragMode(QtWidgets.QGraphicsView.RubberBandDrag)
        self.view.setFocusPolicy(QtCore.Qt.StrongFocus)

        # レイアウト
        container = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(container)
        layout.addWidget(self.view)

        # 操作ボタン群
        btn_layout = QtWidgets.QHBoxLayout()
        self.btn_load_source = QtWidgets.QPushButton("Load Source")
        self.btn_load_target = QtWidgets.QPushButton("Load Target")
        self.btn_connect = QtWidgets.QPushButton("Connect")
        self.btn_delete = QtWidgets.QPushButton("選択削除")

        # Tooltips
        self.btn_load_source.setToolTip("選択中のノードを Source として設定します。\nShift: 現在の Source を選択\nAlt: Target の自動取得を省略")
        self.btn_load_target.setToolTip("選択中のノードを Target として設定します。\nShift: 現在の Target を選択\nAlt: Source の自動取得を省略")
        self.btn_connect.setToolTip("UI上のワイヤを基に接続や DrivenKey を設定します")
        self.btn_delete.setToolTip("選択中のワイヤを削除します")

        self.btn_load_source.clicked.connect(self.load_source)
        self.btn_load_target.clicked.connect(self.load_target)
        self.btn_connect.clicked.connect(self.apply_connections)
        self.btn_delete.clicked.connect(self.delete_selected_lines)

        for b in [self.btn_load_source, self.btn_load_target, self.btn_connect, self.btn_delete]:
            btn_layout.addWidget(b)

        layout.addLayout(btn_layout)
        self.setCentralWidget(container)

        self.populate_ports()

    def populate_ports(self):
        trs = ["Translate", "Rotate", "Scale"]
        axes = ["X", "Y", "Z"]
        spacing = 20
        start_y = 20

        def add_trs_port(side, attr_x, axis_x, port_x):
            y = start_y
            ports = []
            for t in trs:
                self.scene.addText(t).setPos(attr_x, y - 15)
                for a in axes:
                    axis_name = f"{t}{a}_{side}"
                    self.scene.addText(a).setPos(axis_x, y - 10)
                    port = PortItem(axis_name, side=side)
                    port.setPos(port_x, y)
                    self.scene.addItem(port)
                    ports.append(port)
                    y += spacing
                y += 10
            return ports

        self.left_ports = add_trs_port("L", 10, 40, 80)
        self.right_ports = add_trs_port("R", 300, 280, 300)

    # ==== ボタン機能 ====
    def load_source(self):
        mods = QtWidgets.QApplication.keyboardModifiers()
        if mods & QtCore.Qt.ShiftModifier:
            cmds.select(self.source_node)
            return
        sel = cmds.ls(sl=True)
        if sel:
            self.source_node = sel[0]
            print(f"Source loaded: {self.source_node}")
            if not mods & QtCore.Qt.AltModifier:
                self.target_node = []
                cons = cmds.listConnections(self.source_node, d=True) or []
                if cons:
                    for nd in cons:
                        if cmds.nodeType(nd) == "animCurve":
                            tgt = cmds.listConnections(nd, d=True)[0]
                            if not tgt in self.target_node:
                                self.target_node.append(tgt)
                        elif cmds.nodeType(nd) == "transform" and not nd in self.target_node:
                            self.target_node.append(nd)
                    print(f"Auto-loaded Target: {self.target_node}")
            self.sync_connections_from_maya()

    def load_target(self):
        mods = QtWidgets.QApplication.keyboardModifiers()
        if mods & QtCore.Qt.ShiftModifier:
            cmds.select(self.target_node)
            return
        sel = cmds.ls(sl=True)
        if sel:
            self.target_node = sel
            print(f"Target loaded: {self.target_node}")

            if not mods & QtCore.Qt.AltModifier:
                self.source_node = None
                for tgt in self.target_node:
                    cons = cmds.listConnections(tgt, s=True) or []
                    for nd in cons:
                        if cmds.nodeType(nd) == "animCurve":
                            sor = cmds.listConnections(nd, s=True)[0]
                            self.source_node = sor
                            break
                        elif cmds.nodeType(nd) == "transform":
                            self.source_node = nd
                            break
                    if self.source_node:
                        print(f"Auto-loaded Source: {self.source_node}")
                        break
            self.sync_connections_from_maya()

    def delete_selected_lines(self):
        for item in self.scene.selectedItems():
            if isinstance(item, WireLine):
                for port in self.left_ports + self.right_ports:
                    if item in port.connected_lines:
                        port.connected_lines.remove(item)
                self.scene.wire_items.remove(item)
                self.scene.removeItem(item)

    def assemble_fullpath(self, node, wire):
        return f"{node}.{wire.get_source_port().get_attr_name()}"

    def apply_connections(self):
        if not self.source_node or not self.target_node:
            print("Source or Target not loaded!")
            return

        # ---- UIワイヤからConnectAttrの接続ペアを収集 ----
        current_connect_pairs = set()
        for line in self.scene.wire_items:
            if line.connection_type == "connect":
                src_full = self.assemble_fullpath(self.source_node, line)
                for tgt in self.target_node:
                    tgt_full = f"{tgt}.{line.get_target_port().get_attr_name()}"
                    current_connect_pairs.add((src_full, tgt_full))

        # ---- Mayaシーン上の現行接続を確認し、UIにないものは解除 ----
        for tgt in self.target_node:
            for right_port in self.right_ports:
                tgt_full = f"{tgt}.{right_port.get_attr_name()}"
                existing = cmds.listConnections(tgt_full, s=True, d=False, plugs=True) or []
                for conn in existing:
                    pair = (conn, tgt_full)
                    if pair not in current_connect_pairs:
                        try:
                            cmds.disconnectAttr(conn, tgt_full)
                            print(f"Disconnected: {conn} -> {tgt_full}")
                        except Exception as e:
                            print(f"Failed to disconnect {conn}: {e}")

        # ---- UIワイヤを順に処理（Connect or Driven）----
        selected_items = self.scene.selectedItems()  # 選択中ワイヤ
        for line in self.scene.wire_items:
            src_full = self.assemble_fullpath(self.source_node, line)
            tgt_full_array = [self.assemble_fullpath(nd, line) for nd in self.target_node]

            if line.connection_type == "connect":
                # 接続を新規設定
                for tgt_full in tgt_full_array:
                    existing = cmds.listConnections(tgt_full, s=True, d=False, plugs=True)
                    if existing:
                        for conn in existing:
                            try:
                                cmds.disconnectAttr(conn, tgt_full)
                            except:
                                pass
                    try:
                        cmds.connectAttr(src_full, tgt_full, force=True)
                        print(f"Connected: {src_full} -> {tgt_full}")
                    except Exception as e:
                        print(f"Connect failed: {e}")

            elif line.connection_type == "driven":
                # 選択されている DrivenKey ワイヤのみキー打ち
                if line in selected_items or not selected_items:
                    for tgt_full in tgt_full_array:
                        try:
                            cmds.setDrivenKeyframe(tgt_full, currentDriver=src_full)
                            print(f"DrivenKey set: {src_full} -> {tgt_full}")
                        except Exception as e:
                            print(f"DrivenKey failed: {e}")

        # ---- Constraint削除（ワイヤが存在しない場合）----
        has_constraint_wire = any(line.connection_type == "constraint" for line in self.scene.wire_items)
        if not has_constraint_wire:
            # listConnections does not accept a list for the "type" flag, so gather each constraint type separately
            constraint_types = ["parentConstraint", "pointConstraint", "orientConstraint", "scaleConstraint"]
            constraints = []
            for ctype in constraint_types:
                constraints.extend(cmds.listConnections(self.target_node, type=ctype) or [])
            constraints = list(set(constraints))

            for con in constraints:
                drivers = cmds.listConnections(con + ".target", s=True, d=False) or []
                if self.source_node in drivers:
                    try:
                        cmds.delete(con)
                        print(f"Deleted Constraint: {con}")
                    except Exception as e:
                        print(f"Failed to delete constraint {con}: {e}")

    def sync_connections_from_maya(self):
        # すべてのワイヤ削除
        for item in self.scene.wire_items:
            self.scene.wire_items.remove(item)
            self.scene.removeItem(item)
        for port in self.left_ports + self.right_ports:
            port.connected_lines.clear()

        if not self.source_node or not self.target_node:
            return

        def draw_line(source_port, target_port, color, connection_type):
            line = WireLine(source_port.scenePos(), target_port.scenePos(), color=color, connection_type=connection_type)
            line.connected_ports = [source_port, target_port]
            self.scene.addItem(line)
            self.scene.wire_items.append(line)
            source_port.connected_lines.append(line)
            target_port.connected_lines.append(line)

        # 左ポートの各属性についてTarget側接続をチェック
        for left_port in self.left_ports:
            src_full = f"{self.source_node}.{left_port.get_attr_name()}"
            conn = cmds.listConnections(src_full, s=False, d=True, plugs=True)
            if conn:
                # ターゲット側ポートを検索
                tgt_attr = conn[0].split(".")[-1]
                for right_port in self.right_ports:
                    if right_port.get_attr_name() == tgt_attr:
                        draw_line(left_port, right_port, QtCore.Qt.green, "connect")

        # Target側の DrivenKey 情報取得
        for right_port in self.right_ports:
            # DrivenKeyframe が設定されているか確認
            for driven_full in self.target_node:
                driven_full = f"{driven_full}.{right_port.get_attr_name()}"
                driveres = cmds.listConnections(driven_full, type="animCurve", s=True, d=False, plugs=True) or []
                if driveres:
                    driver = driveres[0].split(".")[0]
                    driver_attr = cmds.listConnections(driver, s=True, d=False, plugs=True)[0].split(".")[-1]
                    # Driver ポート探索
                    for left_port in self.left_ports:
                        if left_port.get_attr_name() == driver_attr:
                            draw_line(left_port, right_port, QtCore.Qt.blue, "driven")
                    break

        # --- Constraint 状態チェック ---
        constraint_types = ["parentConstraint", "pointConstraint", "orientConstraint", "scaleConstraint"]
        constraints = []
        for ctype in constraint_types:
            constraints.extend(cmds.listConnections(self.target_node, type=ctype) or [])
        constraints = list(set(constraints))
        for con in constraints:
            con_type = cmds.nodeType(con)
            drivers = cmds.listConnections(con + ".target", s=True, d=False) or []
            if self.source_node not in drivers:
                continue

            if con_type == "parentConstraint":
                trs_groups = ["Translate", "Rotate"]
            elif con_type == "pointConstraint":
                trs_groups = ["Translate"]
            elif con_type == "orientConstraint":
                trs_groups = ["Rotate"]
            elif con_type == "scaleConstraint":
                trs_groups = ["Scale"]
            else:
                trs_groups = []

            for trs in trs_groups:
                left_port = next(p for p in self.left_ports if p.name.startswith(trs) and p.name.endswith("X_L"))
                right_port = next(p for p in self.right_ports if p.name.startswith(trs) and p.name.endswith("X_R"))
                draw_line(left_port, right_port, QtCore.Qt.magenta, "constraint", bezier=True)

# ===== 起動 =====
def show_ui():
    for w in QtWidgets.QApplication.topLevelWidgets():
        if isinstance(w, NodeEditorWindow):
            w.close()

    win = NodeEditorWindow(get_maya_window())
    win.show()


