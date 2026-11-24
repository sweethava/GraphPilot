// Claude chat panel for Substance Designer.
// Only the base QtQuick module is available in Designer (no Layouts/Controls).
import QtQuick

Rectangle {
    id: root
    color: theme.bg

    // UI strings for the current language (backend.tr is a map: key -> text)
    readonly property var tx: backend.tr

    // Colour themes. Every grey is a neutral tone tinted toward the theme's colour, so a theme
    // is just {tint, accent}. Primary buttons, the send button and the status dot use the accent.
    readonly property var palettes: ({
        graphite: { tint: "#00000000", accent: "#ececee", accentHover: "#ffffff", onAccent: "#1e1e20", ok: "#5fbf86" },
        designer: { tint: "#1199e83f", accent: "#99e83f", accentHover: "#b2f566", onAccent: "#1e3101", ok: "#99e83f" },
        midnight: { tint: "#145b8cff", accent: "#8fb4ff", accentHover: "#abc8ff", onAccent: "#0c1a36", ok: "#8fb4ff" },
        ember:    { tint: "#10ff8a3d", accent: "#ff9a52", accentHover: "#ffb27a", onAccent: "#2b1203", ok: "#ff9a52" }
    })
    readonly property var pal: palettes[backend.theme] || palettes.graphite
    function tone(c) { return Qt.tint(c, pal.tint) }
    function toneText(c) { var t = Qt.color(pal.tint); return Qt.tint(c, Qt.rgba(t.r, t.g, t.b, t.a / 3)) }

    QtObject {
        id: theme
        readonly property color bg: root.tone("#1e1e20")
        readonly property color surface: root.tone("#2a2a2d")      // header buttons, user bubble
        readonly property color composer: root.tone("#2c2c2f")
        readonly property color hover: root.tone("#343438")
        readonly property color line: root.tone("#323235")
        readonly property color menu: root.tone("#2f2f33")
        readonly property color menuLine: root.tone("#3e3e43")
        readonly property color card: root.tone("#26262a")
        readonly property color sheet: root.tone("#252528")         // settings dialog
        readonly property color sidebar: root.tone("#19191b")       // chat list drawer
        readonly property color field: root.tone("#232326")
        readonly property color raised: root.tone("#2e2e32")
        readonly property color rowHot: root.tone("#242427")
        readonly property color well: root.tone("#1c1c1e")          // segmented controls
        readonly property color wellSel: root.tone("#3a3a3f")
        readonly property color chip: root.tone("#38383c")
        readonly property color chipHover: root.tone("#424247")
        readonly property color outline: root.tone("#4a4a4f")
        readonly property color focusLine: root.tone("#3c3c40")
        readonly property color selection: root.tone("#55555c")
        readonly property color scroll: root.tone("#55555a")
        readonly property color tip: root.tone("#0f0f10")
        readonly property color imageBg: root.tone("#151517")
        readonly property color text: root.toneText("#ececee")
        readonly property color body: root.toneText("#e2e2e4")
        readonly property color dim: root.toneText("#9a9a9f")
        readonly property color faint: root.toneText("#6c6c71")
        readonly property color error: "#e46a63"
        readonly property color accent: pal.accent
        readonly property color accentHover: pal.accentHover
        readonly property color onAccent: pal.onAccent
        readonly property color ok: pal.ok
        readonly property string font: backend.fontFamily
        readonly property int fs: 13
    }

    function icon(name) { return Qt.resolvedUrl("icons/" + name + ".svg") }

    property bool showSteps: true
    property int lastAssistant: -1

    ListModel { id: messages }

    Connections {
        target: backend
        function onMessageAppended(role, text, image, chip) {
            messages.append({ role: role, text: text, image: image, chip: chip || "" })
            if (role === "assistant") root.lastAssistant = messages.count - 1
            list.stickToBottom()
        }
        function onLastTextUpdated(text) {
            if (root.lastAssistant >= 0) messages.setProperty(root.lastAssistant, "text", text)
            list.stickToBottom()
        }
        function onCleared() { messages.clear(); root.lastAssistant = -1; list.atBottom = true }
        function onFocusInput() { root.closePopups(); input.forceActiveFocus() }
    }

    function submit() {
        var t = input.text.trim()
        if ((!t && backend.images.length === 0) || backend.busy) return
        list.atBottom = true
        backend.send(t)
        input.text = ""
    }

    function greeting() {
        var h = new Date().getHours()
        if (h < 5) return tx.greet_night
        if (h < 12) return tx.greet_morning
        if (h < 18) return tx.greet_day
        return tx.greet_evening
    }

    function closePopups() { modelMenu.visible = false; plusMenu.visible = false; choice.visible = false }

    // ============================================================ header
    Item {
        id: header
        anchors { top: parent.top; left: parent.left; right: parent.right }
        height: 52

        SquareButton {
            id: histBtn
            anchors { left: parent.left; leftMargin: 12; verticalCenter: parent.verticalCenter }
            iconName: "history"; tipItem: tooltip
            active: drawer.open
            tip: tx.chats
            onClicked: drawer.open = !drawer.open
        }

        SquareButton {
            id: newBtn
            anchors { left: histBtn.right; leftMargin: 6; verticalCenter: parent.verticalCenter }
            iconName: "new"; tipItem: tooltip
            tip: tx.new_chat
            onClicked: { backend.newChat(); input.forceActiveFocus() }
        }

        Rectangle {
            id: pill
            anchors.centerIn: parent
            height: 30
            width: Math.min(pillRow.width + 28, header.width - 180)
            radius: 6
            color: theme.surface
            Row {
                id: pillRow
                anchors.centerIn: parent
                spacing: 7
                Rectangle {
                    id: dot
                    anchors.verticalCenter: parent.verticalCenter
                    width: 6; height: 6; radius: 3
                    color: backend.busy ? "#f2f2f3" : theme.ok
                    SequentialAnimation on opacity {
                        running: backend.busy; loops: Animation.Infinite
                        NumberAnimation { to: 0.25; duration: 550 }
                        NumberAnimation { to: 1.0; duration: 550 }
                        onStopped: dot.opacity = 1
                    }
                }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    width: Math.min(implicitWidth, header.width - 222)
                    elide: Text.ElideRight
                    text: backend.status !== "" ? backend.status
                          : (backend.graphName !== "" ? backend.graphName : "Substance Designer")
                    color: theme.text
                    font.family: theme.font; font.pixelSize: 13; font.weight: Font.Normal
                }
            }
            MouseArea { anchors.fill: parent; onClicked: backend.refreshGraph() }
        }

        SquareButton {
            anchors { right: parent.right; rightMargin: 12; verticalCenter: parent.verticalCenter }
            iconName: root.showSteps ? "steps" : "steps_off"; tipItem: tooltip
            active: root.showSteps
            tip: root.showSteps ? tx.hide_steps : tx.show_steps
            onClicked: root.showSteps = !root.showSteps
        }
    }

    // ============================================================ messages
    ListView {
        id: list
        anchors { top: header.bottom; left: parent.left; right: parent.right; bottom: setupCard.visible ? setupCard.top : composer.top; bottomMargin: 8 }
        clip: true
        model: messages
        spacing: 0
        topMargin: 8
        bottomMargin: 8
        boundsBehavior: Flickable.StopAtBounds
        cacheBuffer: 600

        property bool atBottom: true
        onMovementEnded: atBottom = (contentY + height >= contentHeight + bottomMargin - 30)
        function stickToBottom() { if (atBottom) Qt.callLater(positionViewAtEnd) }

        delegate: Item {
            id: row
            width: ListView.view.width
            height: loader.item && loader.active ? loader.item.height + gap : 0
            visible: height > 0
            property bool isTool: model.role === "tool"
            property string prevRole: index > 0 ? messages.get(index - 1).role : ""
            // spacing rules: tight between tool steps, airy between turns
            property int gap: isTool ? (prevRole === "tool" ? 2 : 10)
                              : (model.role === "assistant" && prevRole === "assistant") ? 6
                              : (prevRole === "userimage" && (model.role === "user" || model.role === "userimage")) ? 6 : 14
            opacity: 0
            Component.onCompleted: appear.start()
            NumberAnimation { id: appear; target: row; property: "opacity"; to: 1; duration: 200; easing.type: Easing.OutCubic }

            Loader {
                id: loader
                y: row.gap
                width: parent.width
                active: !row.isTool || root.showSteps
                property string mText: model.text
                property string mImage: model.image
                property string mChip: model.chip !== undefined ? model.chip : ""
                property int mIndex: index
                sourceComponent: model.role === "user" ? userMsg
                               : model.role === "assistant" ? botMsg
                               : model.role === "tool" ? toolMsg
                               : model.role === "image" ? imageMsg
                               : model.role === "userimage" ? userImageMsg
                               : errorMsg
            }
        }

        footer: Item {
            width: list.width
            height: backend.busy && (backend.phase === "thinking" || backend.phase === "tool") ? 34 : 0
            visible: height > 0
            Row {
                x: 18; y: 14; spacing: 5
                Repeater {
                    model: 3
                    Rectangle {
                        width: 6; height: 6; radius: 3; color: theme.dim
                        SequentialAnimation on opacity {
                            running: true; loops: Animation.Infinite
                            PauseAnimation { duration: index * 150 }
                            NumberAnimation { to: 0.2; duration: 360 }
                            NumberAnimation { to: 1.0; duration: 360 }
                            PauseAnimation { duration: (2 - index) * 150 }
                        }
                    }
                }
            }
        }
    }

    WheelScroll {
        anchors.fill: list
        view: list
        onScrolled: list.atBottom = (goal + list.height >= list.contentHeight + list.bottomMargin - 30)
    }

    // thin scrollbar
    Rectangle {
        anchors.right: list.right
        anchors.rightMargin: 3
        width: 4; radius: 2
        color: theme.scroll
        visible: list.contentHeight > list.height
        opacity: list.moving ? 0.9 : 0.35
        Behavior on opacity { NumberAnimation { duration: 250 } }
        y: list.y + list.visibleArea.yPosition * list.height
        height: Math.max(24, list.visibleArea.heightRatio * list.height)
    }

    // empty state
    Column {
        anchors.centerIn: list
        anchors.verticalCenterOffset: -10
        visible: messages.count === 0
        spacing: 14
        width: list.width - 48
        Image {
            anchors.horizontalCenter: parent.horizontalCenter
            // logo.png is the approved Graphite glow; other themes use recoloured copies (tools/logo_variants.py)
            source: Qt.resolvedUrl(backend.theme === "graphite" ? "icons/logo.png" : "icons/logo_" + backend.theme + ".png")
            width: 63; height: 45      // icons/logo.png is 3x this
            smooth: true; mipmap: true; cache: false
        }
        Text {
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            text: root.greeting()
            color: theme.text
            font.family: theme.font; font.pixelSize: 24; font.weight: Font.Normal
        }
        Text {
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            text: tx.subtitle
            color: theme.faint
            font.family: theme.font; font.pixelSize: 13
        }
    }

    // ============================================================ setup card: install / sign in
    Rectangle {
        id: setupCard
        property var s: backend.setup
        visible: !!(s && s.title)
        anchors { left: parent.left; right: parent.right; bottom: composer.top; leftMargin: 12; rightMargin: 12; bottomMargin: 8 }
        height: visible ? setupCol.height + 28 : 0
        radius: 12
        color: theme.card
        border.color: theme.menuLine

        Column {
            id: setupCol
            x: 14; y: 14
            width: parent.width - 28
            spacing: 8

            Row {
                width: parent.width
                spacing: 8
                Row {
                    id: setupDots
                    visible: !!setupCard.s.busy
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 4
                    Repeater {
                        model: 3
                        Rectangle {
                            width: 5; height: 5; radius: 2.5; color: theme.dim
                            SequentialAnimation on opacity {
                                running: setupDots.visible; loops: Animation.Infinite
                                PauseAnimation { duration: index * 150 }
                                NumberAnimation { to: 0.2; duration: 360 }
                                NumberAnimation { to: 1.0; duration: 360 }
                                PauseAnimation { duration: (2 - index) * 150 }
                            }
                        }
                    }
                }
                Text {
                    width: parent.width - (setupDots.visible ? setupDots.width + 8 : 0)
                    text: setupCard.s.title || ""
                    color: theme.text; wrapMode: Text.Wrap
                    font.family: theme.font; font.pixelSize: 14; font.weight: Font.Medium
                }
            }
            Text {
                width: parent.width
                visible: text !== ""
                text: setupCard.s.text || ""
                color: theme.dim; wrapMode: Text.Wrap
                maximumLineCount: 5; elide: Text.ElideRight
                font.family: theme.font; font.pixelSize: 12
            }
            Row {
                spacing: 8
                Rectangle {
                    visible: !!setupCard.s.button
                    width: primT.implicitWidth + 28; height: 30; radius: 8
                    color: primMa.containsMouse ? theme.accentHover : theme.accent
                    Text { id: primT; anchors.centerIn: parent; text: setupCard.s.button || ""; color: theme.onAccent; font.family: theme.font; font.pixelSize: 12; font.weight: Font.Medium }
                    MouseArea { id: primMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: backend.runSetup() }
                }
                Rectangle {
                    visible: !!setupCard.s.url
                    width: pageT.implicitWidth + 24; height: 30; radius: 8
                    color: pageMa.containsMouse ? theme.hover : theme.surface
                    Text { id: pageT; anchors.centerIn: parent; text: (setupCard.s.openPage || "") + " ↗"; color: theme.text; font.family: theme.font; font.pixelSize: 12 }
                    MouseArea { id: pageMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: backend.openSetupPage() }
                }
                Rectangle {
                    width: canT.implicitWidth + 24; height: 30; radius: 8
                    color: canMa.containsMouse ? theme.hover : "transparent"
                    Text { id: canT; anchors.centerIn: parent; text: setupCard.s.cancel || ""; color: theme.dim; font.family: theme.font; font.pixelSize: 12 }
                    MouseArea { id: canMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: backend.cancelSetup() }
                }
            }
        }
    }

    // ============================================================ composer
    Rectangle {
        id: composer
        anchors { left: parent.left; right: parent.right; bottom: parent.bottom; margins: 12 }
        height: (attachBar.visible ? attachBar.height + 10 : 0) + inputArea.height + 48
        radius: 14
        color: theme.composer
        border.color: input.activeFocus ? theme.focusLine : "transparent"
        Behavior on border.color { ColorAnimation { duration: 150 } }

        // attachments: node chip + screenshot thumbnails
        Flow {
            id: attachBar
            x: 12; y: 12
            width: parent.width - 24
            spacing: 6
            visible: backend.attachmentLabel !== "" || backend.images.length > 0   // not chip.visible: a child of a hidden item is never visible

            Rectangle {
                id: chip
                visible: backend.attachmentLabel !== ""
                height: 26
                width: chipRow.width + 20
                radius: 7
                color: chipMa.containsMouse && !xMa.containsMouse ? theme.chipHover : theme.chip
                Behavior on color { ColorAnimation { duration: 120 } }
                MouseArea {
                    id: chipMa
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: { tooltip.hide(); backend.focusAttachment() }
                    onContainsMouseChanged: containsMouse ? tooltip.showFor(chip, tx.show_nodes) : tooltip.hide()
                }
                Row {
                    id: chipRow
                    anchors.centerIn: parent
                    spacing: 6
                    Image { anchors.verticalCenter: parent.verticalCenter; source: root.icon("node"); sourceSize: Qt.size(14, 14); width: 14; height: 14 }
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: backend.attachmentLabel
                        color: theme.text; font.family: theme.font; font.pixelSize: 12
                    }
                    Image {
                        anchors.verticalCenter: parent.verticalCenter
                        source: root.icon("x"); sourceSize: Qt.size(12, 12); width: 12; height: 12
                        opacity: xMa.containsMouse ? 1 : 0.6
                        MouseArea { id: xMa; anchors.fill: parent; anchors.margins: -5; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: backend.clearAttachment() }
                    }
                }
            }

            Repeater {
                model: backend.images
                Rectangle {
                    width: 56; height: 56; radius: 8
                    color: theme.chip
                    clip: true
                    Image {
                        anchors.fill: parent
                        source: backend.thumb(modelData, 56, 56, 8)
                        smooth: true; mipmap: true; asynchronous: true
                    }
                    MouseArea { id: thMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: backend.openUrl(modelData) }
                    Rectangle {
                        anchors { top: parent.top; right: parent.right; margins: 3 }
                        width: 18; height: 18; radius: 9
                        color: rmMa.containsMouse ? "#000000" : "#cc111113"
                        visible: thMa.containsMouse || rmMa.containsMouse
                        Image { anchors.centerIn: parent; source: root.icon("x"); sourceSize: Qt.size(10, 10); width: 10; height: 10 }
                        MouseArea { id: rmMa; anchors.fill: parent; anchors.margins: -3; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: backend.removeImage(index) }
                    }
                }
            }
        }

        Flickable {
            id: inputArea
            anchors { left: parent.left; right: parent.right; leftMargin: 16; rightMargin: 14 }
            y: attachBar.visible ? attachBar.y + attachBar.height + 6 : 6
            height: Math.min(Math.max(input.contentHeight + 16, 34), 150)
            contentWidth: width
            contentHeight: input.contentHeight + 16
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            function ensureVisible(r) {
                if (contentY >= r.y) contentY = r.y
                else if (contentY + height <= r.y + r.height + 8) contentY = r.y + r.height + 8 - height
            }
            TextEdit {
                id: input
                width: inputArea.width
                y: 8
                color: theme.text
                wrapMode: TextEdit.Wrap
                font.family: theme.font; font.pixelSize: 14
                selectByMouse: true
                selectionColor: theme.selection
                focus: true
                onCursorRectangleChanged: inputArea.ensureVisible(cursorRectangle)
                Keys.onPressed: function(e) {
                    if ((e.matches(StandardKey.Paste) || (e.key === Qt.Key_Insert && (e.modifiers & Qt.ShiftModifier)))
                            && backend.pasteImage()) {
                        e.accepted = true; return
                    }
                    if ((e.key === Qt.Key_Return || e.key === Qt.Key_Enter) && !(e.modifiers & Qt.ShiftModifier)) {
                        root.submit(); e.accepted = true
                    }
                }
                Text {
                    visible: input.text.length === 0
                    text: tx.placeholder
                    color: theme.faint
                    font: input.font
                }
            }
            MouseArea { anchors.fill: parent; acceptedButtons: Qt.NoButton; cursorShape: Qt.IBeamCursor }
        }

        // bottom toolbar
        Item {
            anchors { left: parent.left; right: parent.right; bottom: parent.bottom; margins: 10 }
            height: 30

            Rectangle {
                id: plusBtn
                anchors { left: parent.left; verticalCenter: parent.verticalCenter }
                width: 28; height: 28; radius: 14
                color: plusMa.containsMouse ? theme.hover : "transparent"
                border.color: theme.outline; border.width: 1
                Image { anchors.centerIn: parent; source: root.icon("plus"); sourceSize: Qt.size(16, 16); width: 16; height: 16 }
                MouseArea {
                    id: plusMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                    onClicked: { tooltip.hide(); var v = !plusMenu.visible; root.closePopups(); plusMenu.visible = v }
                    onContainsMouseChanged: containsMouse && !plusMenu.visible ? tooltip.showFor(plusBtn, tx.attach) : tooltip.hide()
                }
            }

            // model picker
            Rectangle {
                id: modelBtn
                anchors { right: sendBtn.left; rightMargin: 8; verticalCenter: parent.verticalCenter }
                height: 28
                width: modelRow.width + 18
                radius: 7
                color: modelMa.containsMouse || modelMenu.visible ? theme.hover : "transparent"
                Row {
                    id: modelRow
                    anchors.centerIn: parent
                    spacing: 4
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: backend.modelLabel
                        color: theme.text; font.family: theme.font; font.pixelSize: 13
                    }
                    Image { anchors.verticalCenter: parent.verticalCenter; source: root.icon("chevron"); sourceSize: Qt.size(14, 14); width: 14; height: 14 }
                }
                MouseArea {
                    id: modelMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                    onClicked: { var v = !modelMenu.visible; root.closePopups(); modelMenu.visible = v }
                }
            }

            Rectangle {
                id: sendBtn
                anchors { right: parent.right; verticalCenter: parent.verticalCenter }
                width: 30; height: 30; radius: 15
                property bool canSend: input.text.trim().length > 0 || backend.images.length > 0
                color: (backend.busy || canSend) ? (sendMa.containsMouse ? theme.accentHover : theme.accent) : theme.outline
                Behavior on color { ColorAnimation { duration: 140 } }
                scale: sendMa.pressed ? 0.92 : 1
                Behavior on scale { NumberAnimation { duration: 90 } }
                Image {
                    anchors.centerIn: parent
                    source: root.icon(backend.busy ? "stop" : "send")
                    sourceSize: Qt.size(16, 16); width: 16; height: 16
                    opacity: backend.busy || sendBtn.canSend ? 1 : 0.55
                }
                MouseArea {
                    id: sendMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                    onClicked: backend.busy ? backend.stop() : root.submit()
                }
            }
        }
    }

    // click-away for the composer menus
    MouseArea {
        anchors.fill: parent
        visible: modelMenu.visible || plusMenu.visible
        onClicked: root.closePopups()
    }

    // attach menu (opens upwards from "+")
    PopupMenu {
        id: plusMenu
        x: composer.x + 6
        y: composer.y - height - 6
        items: [ { id: "shot", icon: "camera", label: tx.shot_designer },
                 { id: "file", icon: "image", label: tx.image_disk },
                 { id: "paste", icon: "paste", label: tx.paste_clip, hint: Qt.platform.os === "osx" ? "⌘V" : "Ctrl+V" },
                 { id: "nodes", icon: "node", label: tx.selected_nodes, hint: Qt.platform.os === "osx" ? "⌘⇧A" : "Ctrl+Shift+A" } ]
        footnote: tx.drop_hint
        onPicked: function(id) {
            if (id === "shot") backend.grabDesigner()
            else if (id === "file") backend.pickImages()
            else if (id === "paste") { if (!backend.pasteImage()) backend.setStatusText(tx.no_clip_image) }
            else backend.attachSelection()
            input.forceActiveFocus()
        }
    }

    // model menu (opens upwards from the model button)
    PopupMenu {
        id: modelMenu
        x: Math.min(composer.x + composer.width - width - 10, root.width - width - 8)
        y: composer.y - height - 6
        items: backend.models
        selected: backend.model
        onPicked: function(id) { backend.setModel(id) }
    }

    // drag & drop images anywhere on the panel
    DropArea {
        id: drop
        anchors.fill: parent
        z: 90
        onEntered: function(d) { d.accepted = d.hasUrls }
        onDropped: function(d) { if (d.hasUrls) { backend.addFiles(d.urls); d.acceptProposedAction() } }
        Rectangle {
            anchors.fill: parent
            anchors.margins: 8
            visible: drop.containsDrag
            radius: 14
            color: Qt.rgba(theme.bg.r, theme.bg.g, theme.bg.b, 0.8)
            border.color: theme.faint; border.width: 1
            Column {
                anchors.centerIn: parent
                spacing: 10
                Image { anchors.horizontalCenter: parent.horizontalCenter; source: root.icon("image"); sourceSize: Qt.size(28, 28); width: 28; height: 28 }
                Text { text: tx.drop_release; color: theme.text; font.family: theme.font; font.pixelSize: 14 }
            }
        }
    }

    // ============================================================ chat list drawer
    Rectangle {
        anchors.fill: parent
        z: 60
        color: "#000000"
        opacity: drawer.open ? 0.45 : 0
        visible: opacity > 0
        Behavior on opacity { NumberAnimation { duration: 180 } }
        MouseArea { anchors.fill: parent; hoverEnabled: true; onClicked: drawer.open = false }
    }

    Rectangle {
        id: drawer
        property bool open: false
        property string editing: ""      // id of the chat being renamed
        onOpenChanged: {
            root.closePopups(); tooltip.hide(); editing = ""
            if (!open) { search.text = ""; input.forceActiveFocus() }
        }
        z: 61
        width: Math.min(300, root.width - 48)
        height: root.height
        x: open ? 0 : -width - 2
        visible: x > -width - 2
        Behavior on x { NumberAnimation { duration: 200; easing.type: Easing.OutCubic } }
        color: theme.sidebar
        Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: theme.line }
        MouseArea { anchors.fill: parent; hoverEnabled: true; onClicked: drawer.editing = "" }

        Item {
            id: dHead
            width: parent.width; height: 52
            Text {
                x: 18; anchors.verticalCenter: parent.verticalCenter
                text: tx.chats
                color: theme.text; font.family: theme.font; font.pixelSize: 15; font.weight: Font.Medium
            }
            SquareButton {
                anchors { right: parent.right; rightMargin: 12; verticalCenter: parent.verticalCenter }
                iconName: "x"; tipItem: tooltip; tip: tx.close
                onClicked: drawer.open = false
            }
        }

        DrawerRow {
            id: dNew
            y: dHead.height
            iconName: "new"; label: tx.new_chat
            onClicked: { backend.newChat(); drawer.open = false }
        }

        // search
        Rectangle {
            id: searchBox
            x: 8; anchors.top: dNew.bottom; anchors.topMargin: 6
            width: parent.width - 16; height: 32; radius: 8
            color: theme.field
            border.color: search.activeFocus ? theme.focusLine : "transparent"
            Image { x: 10; anchors.verticalCenter: parent.verticalCenter; source: root.icon("search"); sourceSize: Qt.size(14, 14); width: 14; height: 14; opacity: 0.7 }
            TextInput {
                id: search
                x: 32; width: parent.width - 60
                anchors.verticalCenter: parent.verticalCenter
                color: theme.text; selectionColor: theme.selection
                font.family: theme.font; font.pixelSize: 13
                clip: true
                onTextChanged: backend.chatModel.setFilter(text)
                Keys.onEscapePressed: text.length ? text = "" : drawer.open = false
                Keys.onShortcutOverride: function(e) { if (e.key === Qt.Key_Escape) e.accepted = true }
                Text { visible: !search.text.length; text: tx.search; color: theme.faint; font: search.font }
            }
            Image {
                anchors { right: parent.right; rightMargin: 9; verticalCenter: parent.verticalCenter }
                visible: search.text.length > 0
                source: root.icon("x"); sourceSize: Qt.size(12, 12); width: 12; height: 12; opacity: 0.7
                MouseArea { anchors.fill: parent; anchors.margins: -5; cursorShape: Qt.PointingHandCursor; onClicked: search.text = "" }
            }
        }

        Text {
            id: dCaption
            x: 18; anchors.top: searchBox.bottom; anchors.topMargin: 14
            text: tx.recent
            color: theme.faint; font.family: theme.font; font.pixelSize: 11
        }

        ListView {
            id: chatList
            anchors { top: dCaption.bottom; topMargin: 6; left: parent.left; right: parent.right; bottom: dFoot.top; bottomMargin: 4 }
            clip: true
            spacing: 2
            boundsBehavior: Flickable.StopAtBounds
            reuseItems: true
            interactive: contentHeight > height
            model: backend.chatModel
            delegate: Item {
              // ListView positions delegates at x=0, so the side margin lives inside the delegate
              width: ListView.view.width; height: 44
              required property string chatId
              required property string title
              required property string when
              required property bool current
              Rectangle {
                id: cRow
                property string chatId: parent.chatId
                property string title: parent.title
                property string when: parent.when
                property bool current: parent.current
                x: 8
                width: parent.width - 16; height: 44; radius: 8
                property bool hot: cMa.containsMouse || renBtn.hovered || delBtn.hovered || confirm.hovered
                property bool armed: false
                property bool editing: drawer.editing === chatId
                onHotChanged: if (!hot) armed = false
                color: current ? theme.surface : (hot || editing ? theme.rowHot : "transparent")
                Text {
                    x: 10; y: 6
                    visible: !cRow.editing
                    width: parent.width - 20 - (cRow.hot ? (cRow.armed ? confirm.width + 4 : 54) : 0)
                    elide: Text.ElideRight
                    text: cRow.title
                    color: theme.text; font.family: theme.font; font.pixelSize: 13
                }
                Text {
                    x: 10; y: 25
                    text: cRow.when
                    color: theme.faint; font.family: theme.font; font.pixelSize: 11
                }
                MouseArea {
                    id: cMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                    onClicked: { if (cRow.editing) return; drawer.editing = ""; backend.openChat(cRow.chatId); drawer.open = false }
                    onDoubleClicked: drawer.editing = cRow.chatId
                }
                // inline rename
                Rectangle {
                    visible: cRow.editing
                    x: 4; y: 3
                    width: parent.width - 12; height: 22; radius: 5
                    color: theme.raised; border.color: theme.outline
                    TextInput {
                        id: renameField
                        x: 6; width: parent.width - 12
                        anchors.verticalCenter: parent.verticalCenter
                        color: theme.text; selectionColor: theme.selection
                        font.family: theme.font; font.pixelSize: 13
                        clip: true
                        onVisibleChanged: if (visible) { text = cRow.title; selectAll(); forceActiveFocus() }
                        // only Enter saves; Esc or clicking anywhere else cancels
                        onAccepted: { backend.renameChat(cRow.chatId, text); drawer.editing = "" }
                        Keys.onEscapePressed: function(e) { e.accepted = true; drawer.editing = "" }
                        // claim Esc before Designer's own shortcuts get it
                        Keys.onShortcutOverride: function(e) { if (e.key === Qt.Key_Escape) e.accepted = true }
                        onActiveFocusChanged: if (!activeFocus && cRow.editing) drawer.editing = ""
                    }
                }
                Row {
                    anchors { right: parent.right; rightMargin: 6; verticalCenter: parent.verticalCenter }
                    spacing: 2
                    visible: cRow.hot && !cRow.armed && !cRow.editing
                    ActionIcon {
                        id: renBtn
                        iconName: "pencil"; tip: tx.rename; tipItem: tooltip
                        onClicked: drawer.editing = cRow.chatId
                    }
                    ActionIcon {
                        id: delBtn
                        iconName: "trash"; tip: tx.delete; tipItem: tooltip
                        onClicked: cRow.armed = true
                    }
                }
                Rectangle {
                    id: confirm
                    property alias hovered: cfMa.containsMouse
                    anchors { right: parent.right; rightMargin: 8; verticalCenter: parent.verticalCenter }
                    visible: cRow.armed
                    width: cfText.implicitWidth + 16; height: 24; radius: 6
                    color: cfMa.containsMouse ? "#5a2826" : "#3d2221"
                    Text { id: cfText; anchors.centerIn: parent; text: tx.delete; color: theme.error; font.family: theme.font; font.pixelSize: 12 }
                    MouseArea { id: cfMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: backend.deleteChat(cRow.chatId) }
                }
            }
            }
        }
        WheelScroll { anchors.fill: chatList; view: chatList }

        // thin scrollbar for the chat list
        Rectangle {
            anchors.right: chatList.right
            anchors.rightMargin: 2
            width: 3; radius: 1.5
            color: theme.scroll
            visible: chatList.contentHeight > chatList.height
            opacity: chatList.moving ? 0.9 : 0.35
            y: chatList.y + chatList.visibleArea.yPosition * chatList.height
            height: Math.max(20, chatList.visibleArea.heightRatio * chatList.height)
        }

        Text {
            anchors.centerIn: chatList
            visible: chatList.count === 0
            text: backend.chatModel.total === 0 ? tx.no_chats : tx.no_results
            color: theme.faint; font.family: theme.font; font.pixelSize: 12
        }

        // footer: divider + settings row with its own padding (hover must not touch the line)
        Item {
            id: dFoot
            anchors.bottom: parent.bottom
            width: parent.width - 1; height: 53
            Rectangle { width: parent.width; height: 1; color: theme.line }
            DrawerRow {
                y: 9
                iconName: "gear"; label: tx.settings
                onClicked: settings.open = true
            }
        }
    }

    // ============================================================ settings
    Rectangle {
        anchors.fill: parent
        z: 70
        color: "#000000"
        opacity: settings.open ? 0.55 : 0
        visible: opacity > 0
        Behavior on opacity { NumberAnimation { duration: 160 } }
        MouseArea { anchors.fill: parent; hoverEnabled: true; onClicked: settings.open = false }
    }

    Rectangle {
        id: settings
        property bool open: false
        onOpenChanged: { choice.visible = false; if (open) backend.refreshAgents() }
        z: 71
        visible: opacity > 0
        opacity: open ? 1 : 0
        scale: open ? 1 : 0.97
        Behavior on opacity { NumberAnimation { duration: 160 } }
        Behavior on scale { NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }
        width: Math.min(340, root.width - 32)
        height: setCol.height + 32
        x: (root.width - width) / 2
        y: Math.max(16, Math.min((root.height - height) / 2, 64))   // high enough for the language list
        radius: 14
        color: theme.sheet
        border.color: theme.menuLine
        MouseArea { anchors.fill: parent; onClicked: choice.visible = false }

        Column {
            id: setCol
            x: 16; y: 16
            width: parent.width - 32
            spacing: 14

            Item {
                width: parent.width; height: 28
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: tx.settings
                    color: theme.text; font.family: theme.font; font.pixelSize: 16; font.weight: Font.Medium
                }
                ActionIcon {
                    anchors { right: parent.right; verticalCenter: parent.verticalCenter }
                    iconName: "x"; onClicked: settings.open = false
                }
            }

            // assistant: Claude Code / Codex (ChatGPT)
            Column {
                width: parent.width; spacing: 6
                Text { text: tx.assistant; color: theme.dim; font.family: theme.font; font.pixelSize: 12 }
                Rectangle {
                    width: parent.width; height: 40; radius: 9
                    color: theme.well
                    Row {
                        x: 3; y: 3
                        Repeater {
                            model: backend.agentList
                            Rectangle {
                                width: (setCol.width - 6) / Math.max(1, backend.agentList.length); height: 34; radius: 7
                                property bool sel: backend.agentSetting === modelData.id
                                color: sel ? theme.wellSel : (aMa.containsMouse ? theme.surface : "transparent")
                                Behavior on color { ColorAnimation { duration: 120 } }
                                Text {
                                    anchors.centerIn: parent
                                    text: modelData.label
                                    color: parent.sel ? theme.text : theme.dim
                                    opacity: modelData.ready ? 1 : 0.6
                                    font.family: theme.font; font.pixelSize: 14
                                }
                                MouseArea { id: aMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: backend.setAgent(modelData.id) }
                            }
                        }
                    }
                }
                Row {
                    id: agentHint
                    property var cur: {
                        var l = backend.agentList
                        for (var i = 0; i < l.length; i++) if (l[i].id === backend.agentSetting) return l[i]
                        return null
                    }
                    visible: !!(cur && cur.hint)
                    spacing: 6
                    Text {
                        text: agentHint.cur ? agentHint.cur.label + ": " + agentHint.cur.hint : ""
                        color: "#e0a060"; font.family: theme.font; font.pixelSize: 11
                    }
                    Text {
                        text: agentHint.cur && agentHint.cur.action ? agentHint.cur.action + " →" : ""
                        color: hintMa.containsMouse ? theme.text : "#f0b878"
                        font.family: theme.font; font.pixelSize: 11; font.weight: Font.Medium
                        font.underline: hintMa.containsMouse
                        MouseArea {
                            id: hintMa
                            anchors.fill: parent; anchors.margins: -4
                            hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                            onClicked: { settings.open = false; backend.startSetup(agentHint.cur.id) }
                        }
                    }
                }
            }

            // language: dropdown
            Column {
                width: parent.width; spacing: 6
                Text { text: tx.language; color: theme.dim; font.family: theme.font; font.pixelSize: 12 }
                Rectangle {
                    id: langBtn
                    width: parent.width; height: 36; radius: 8
                    color: langMa.containsMouse || choice.visible ? theme.hover : theme.surface
                    Image { x: 11; anchors.verticalCenter: parent.verticalCenter; source: root.icon("globe"); sourceSize: Qt.size(15, 15); width: 15; height: 15; opacity: 0.8 }
                    Text {
                        x: 36; anchors.verticalCenter: parent.verticalCenter
                        text: {
                            var l = backend.languages
                            for (var i = 0; i < l.length; i++) if (l[i].id === backend.language) return l[i].label
                            return backend.language
                        }
                        color: theme.text; font.family: theme.font; font.pixelSize: 13
                    }
                    Image { anchors { right: parent.right; rightMargin: 10; verticalCenter: parent.verticalCenter } source: root.icon("chevron"); sourceSize: Qt.size(14, 14); width: 14; height: 14 }
                    MouseArea { id: langMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: choice.visible = !choice.visible }
                }
            }

            // font: segmented, each option previewed in its own typeface
            Column {
                width: parent.width; spacing: 6
                Text { text: tx.font; color: theme.dim; font.family: theme.font; font.pixelSize: 12 }
                Rectangle {
                    width: parent.width; height: 40; radius: 9
                    color: theme.well
                    Row {
                        x: 3; y: 3
                        Repeater {
                            model: backend.fonts
                            Rectangle {
                                width: (setCol.width - 6) / 3; height: 34; radius: 7
                                property bool sel: backend.font === modelData.id
                                color: sel ? theme.wellSel : (fMa.containsMouse ? theme.surface : "transparent")
                                Behavior on color { ColorAnimation { duration: 120 } }
                                Text {
                                    anchors.centerIn: parent
                                    text: modelData.label
                                    color: parent.sel ? theme.text : theme.dim
                                    font.family: modelData.family; font.pixelSize: 14
                                }
                                MouseArea { id: fMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: backend.setFont(modelData.id) }
                            }
                        }
                    }
                }
            }

            // theme: segmented, each option shows its own background and accent
            Column {
                width: parent.width; spacing: 6
                Text { text: tx.theme; color: theme.dim; font.family: theme.font; font.pixelSize: 12 }
                Rectangle {
                    width: parent.width; height: thGrid.height + 6; radius: 9
                    color: theme.well
                    Grid {
                        id: thGrid
                        x: 3; y: 3; columns: 2
                        Repeater {
                            model: backend.themes
                            Rectangle {
                                width: (setCol.width - 6) / 2; height: 34; radius: 7
                                property bool sel: backend.theme === modelData.id
                                property var pp: root.palettes[modelData.id]
                                color: sel ? theme.wellSel : (thmMa.containsMouse ? theme.surface : "transparent")
                                Behavior on color { ColorAnimation { duration: 120 } }
                                Row {
                                    anchors.centerIn: parent
                                    spacing: 6
                                    Rectangle {
                                        anchors.verticalCenter: parent.verticalCenter
                                        width: 12; height: 12; radius: 6
                                        color: Qt.tint("#1e1e20", parent.parent.pp.tint)
                                        border.color: parent.parent.pp.accent; border.width: 3
                                    }
                                    Text {
                                        text: modelData.label
                                        color: parent.parent.sel ? theme.text : theme.dim
                                        font.family: theme.font; font.pixelSize: 12
                                    }
                                }
                                MouseArea { id: thmMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: backend.setTheme(modelData.id) }
                            }
                        }
                    }
                }
            }

            Rectangle {
                width: parent.width; height: 36; radius: 8
                color: doneMa.containsMouse ? theme.accentHover : theme.accent
                Text { anchors.centerIn: parent; text: tx.done; color: theme.onAccent; font.family: theme.font; font.pixelSize: 13; font.weight: Font.Medium }
                MouseArea { id: doneMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: settings.open = false }
            }

            // about: version, author, repo link
            Row {
                anchors.horizontalCenter: parent.horizontalCenter
                spacing: 4
                Text {
                    text: "GraphPilot " + backend.version + " · by"
                    color: theme.dim; opacity: 0.8
                    font.family: theme.font; font.pixelSize: 11
                }
                Text {
                    text: "SweetHava"
                    color: authorMa.containsMouse ? theme.text : theme.dim
                    font.family: theme.font; font.pixelSize: 11
                    font.underline: authorMa.containsMouse
                    MouseArea {
                        id: authorMa
                        anchors.fill: parent; anchors.margins: -4
                        hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                        onClicked: backend.openUrl(backend.authorUrl)
                    }
                }
                Text {
                    text: "·"
                    color: theme.dim; opacity: 0.8
                    font.family: theme.font; font.pixelSize: 11
                }
                Text {
                    text: "GitHub ↗"
                    color: repoMa.containsMouse ? theme.text : theme.dim
                    font.family: theme.font; font.pixelSize: 11
                    font.underline: repoMa.containsMouse
                    MouseArea {
                        id: repoMa
                        anchors.fill: parent; anchors.margins: -4
                        hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                        onClicked: backend.openUrl(backend.repoUrl)
                    }
                }
            }
        }

        // language list (drops down over the rest of the card)
        PopupMenu {
            id: choice
            z: 5
            x: setCol.x
            y: setCol.y + langBtn.parent.y + langBtn.y + langBtn.height + 4
            minWidth: setCol.width
            maxHeight: root.height - settings.y - y - 12
            items: backend.languages
            selected: backend.language
            onPicked: function(id) { backend.setLanguage(id) }
        }
    }

    // tooltip
    Rectangle {
        id: tooltip
        property string text: ""
        visible: false
        z: 100
        color: theme.tip
        radius: 6
        width: tipText.implicitWidth + 16
        height: tipText.implicitHeight + 10
        Text { id: tipText; anchors.centerIn: parent; text: tooltip.text; color: theme.text; font.family: theme.font; font.pixelSize: 12 }
        Timer { id: tipTimer; interval: 450; onTriggered: tooltip.visible = true }
        function showFor(item, t) {
            text = t
            var p = item.mapToItem(root, 0, 0)
            x = Math.max(6, Math.min(p.x + item.width / 2 - width / 2, root.width - width - 6))
            y = p.y + item.height + 6 + height > root.height ? p.y - height - 6 : p.y + item.height + 6
            tipTimer.restart()
        }
        function hide() { tipTimer.stop(); visible = false }
    }

    // ============================================================ components
    // Menu that sizes itself to its widest row. items: [{id, label, hint?, icon?}]
    // Mouse wheel: ~112 px per notch with a short glide (the default Flickable step is tiny).
    // Takes no buttons and no hover, so clicks, text selection and hover reach the items below.
    component WheelScroll: MouseArea {
        id: ws
        property var view
        property real goal: 0
        signal scrolled()
        acceptedButtons: Qt.NoButton
        onWheel: function(wheel) {
            var v = view
            var minY = v.originY - v.topMargin
            var maxY = Math.max(minY, v.originY + v.contentHeight + v.bottomMargin - v.height)
            var touchpad = wheel.pixelDelta.y !== 0
            var dy = touchpad ? wheel.pixelDelta.y : wheel.angleDelta.y / 120 * 112
            goal = Math.max(minY, Math.min(maxY, (wsAnim.running ? goal : v.contentY) - dy))
            v.cancelFlick()
            if (touchpad) { wsAnim.stop(); v.contentY = goal }
            else { wsAnim.to = goal; wsAnim.restart() }
            wheel.accepted = true
            ws.scrolled()
        }
        NumberAnimation { id: wsAnim; target: ws.view; property: "contentY"; duration: 180; easing.type: Easing.OutCubic }
    }

    component PopupMenu: Rectangle {
        id: pm
        property var items: []
        property string selected: ""
        property string footnote: ""
        property real minWidth: 140
        property real maxHeight: 10000
        signal picked(string id)
        visible: false
        z: 50
        radius: 10
        color: theme.menu
        border.color: theme.menuLine
        width: {
            var w = pm.minWidth
            for (var i = 0; i < rep.count; i++) { var it = rep.itemAt(i); if (it) w = Math.max(w, it.need + 10) }
            return Math.max(w, foot.visible ? foot.implicitWidth + 10 : 0)
        }
        height: Math.min(pmCol.height + 10, maxHeight)
        clip: true
        Flickable {
            anchors.fill: parent; anchors.margins: 5
            contentHeight: pmCol.height
            boundsBehavior: Flickable.StopAtBounds
            interactive: contentHeight > height
            Column {
                id: pmCol
                width: parent.width
                Repeater {
                    id: rep
                    model: pm.items
                    Rectangle {
                        width: pmCol.width; height: 34; radius: 7
                        property bool isSel: pm.selected !== "" && pm.selected === modelData.id
                        property real textX: modelData.icon ? 34 : 10
                        // width of the row's content; hint space is kept even when "✓" replaces it
                        property real need: textX + lbl.implicitWidth + 12
                                            + (modelData.hint ? 28 + hintM.implicitWidth : (pm.selected !== "" ? 30 : 0))
                        color: iMa.containsMouse ? theme.hover : "transparent"
                        Image {
                            x: 10; anchors.verticalCenter: parent.verticalCenter
                            visible: !!modelData.icon
                            source: modelData.icon ? root.icon(modelData.icon) : ""
                            sourceSize: Qt.size(15, 15); width: 15; height: 15
                        }
                        Text {
                            id: lbl
                            x: parent.textX; anchors.verticalCenter: parent.verticalCenter
                            text: modelData.label
                            color: theme.text; font.family: theme.font; font.pixelSize: 13
                            font.weight: parent.isSel ? Font.Medium : Font.Normal
                        }
                        Text { id: hintM; visible: false; text: modelData.hint || ""; font.family: theme.font; font.pixelSize: 12 }
                        Text {
                            anchors { right: parent.right; rightMargin: 10; verticalCenter: parent.verticalCenter }
                            text: parent.isSel ? "✓" : (modelData.hint || "")
                            color: parent.isSel ? theme.text : theme.faint
                            font.family: theme.font; font.pixelSize: 12
                        }
                        MouseArea {
                            id: iMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                            onClicked: { pm.visible = false; pm.picked(modelData.id) }
                        }
                    }
                }
                Text {
                    id: foot
                    visible: pm.footnote !== ""
                    width: pmCol.width
                    topPadding: 4; bottomPadding: 4; leftPadding: 10; rightPadding: 10
                    text: pm.footnote
                    color: theme.faint; font.family: theme.font; font.pixelSize: 11
                }
            }
        }
    }

    component DrawerRow: Rectangle {
        id: dr
        property string iconName
        property string label
        signal clicked()
        x: 8
        width: parent.width - 16; height: 36; radius: 8
        color: drMa.containsMouse ? theme.hover : "transparent"
        Row {
            x: 10; anchors.verticalCenter: parent.verticalCenter; spacing: 10
            Image { anchors.verticalCenter: parent.verticalCenter; source: root.icon(dr.iconName); sourceSize: Qt.size(16, 16); width: 16; height: 16 }
            Text { anchors.verticalCenter: parent.verticalCenter; text: dr.label; color: theme.text; font.family: theme.font; font.pixelSize: 13 }
        }
        MouseArea { id: drMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: dr.clicked() }
    }

    component SquareButton: Rectangle {
        id: sb
        property string iconName
        property string tip
        property bool active: false
        property var tipItem: null
        signal clicked()
        width: 32; height: 32; radius: 6
        color: sbMa.containsMouse ? theme.hover : theme.surface
        Image {
            anchors.centerIn: parent
            source: Qt.resolvedUrl("icons/" + sb.iconName + ".svg")
            sourceSize: Qt.size(18, 18); width: 18; height: 18
            opacity: sb.active || sbMa.containsMouse ? 1 : 0.75
        }
        MouseArea {
            id: sbMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
            onContainsMouseChanged: { if (!sb.tipItem) return; if (containsMouse && sb.tip !== "") sb.tipItem.showFor(sb, sb.tip); else sb.tipItem.hide() }
            onClicked: { if (sb.tipItem) sb.tipItem.hide(); sb.clicked() }
        }
    }

    component ActionIcon: Rectangle {
        id: ai
        property string iconName
        property string tip
        property var tipItem: null
        property alias hovered: aiMa.containsMouse
        signal clicked()
        width: 24; height: 24; radius: 5
        color: aiMa.containsMouse ? theme.raised : "transparent"
        Image {
            anchors.centerIn: parent
            source: Qt.resolvedUrl("icons/" + ai.iconName + ".svg")
            sourceSize: Qt.size(15, 15); width: 15; height: 15
            opacity: aiMa.containsMouse ? 1 : 0.7
        }
        MouseArea {
            id: aiMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
            onContainsMouseChanged: { if (!ai.tipItem) return; if (containsMouse && ai.tip !== "") ai.tipItem.showFor(ai, ai.tip); else ai.tipItem.hide() }
            onClicked: { if (ai.tipItem) ai.tipItem.hide(); ai.clicked() }
        }
    }

    Component {
        id: userMsg
        Item {
            width: parent ? parent.width : 0
            height: ub.height
            Rectangle {
                id: ub
                anchors.right: parent.right
                anchors.rightMargin: 14
                // sized from the data, not from .visible: children of a not-yet-shown row report visible=false
                property bool hasChip: mChip !== ""
                property bool hasText: mText !== ""
                width: Math.max(hasText ? ut.width : 0, hasChip ? uchip.width : 0) + 24
                height: (hasChip ? uchip.height : 0) + (hasChip && hasText ? 8 : 0) + (hasText ? ut.height : 0) + 18
                radius: 8
                color: theme.surface
                // attached nodes: same chip as in the composer; click shows them in the graph
                Rectangle {
                    id: uchip
                    visible: ub.hasChip
                    x: 12; y: 9
                    height: 26
                    width: ucRow.width + 20
                    radius: 7
                    color: ucMa.containsMouse ? theme.chipHover : theme.chip
                    Behavior on color { ColorAnimation { duration: 120 } }
                    Row {
                        id: ucRow
                        anchors.centerIn: parent
                        spacing: 6
                        Image { anchors.verticalCenter: parent.verticalCenter; source: root.icon("node"); sourceSize: Qt.size(14, 14); width: 14; height: 14 }
                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            text: mChip
                            color: theme.text; font.family: theme.font; font.pixelSize: 12
                        }
                    }
                    MouseArea {
                        id: ucMa
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: { tooltip.hide(); backend.focusMessageNodes(mIndex) }
                        onContainsMouseChanged: containsMouse ? tooltip.showFor(uchip, tx.show_nodes) : tooltip.hide()
                    }
                }
                TextEdit {
                    id: ut
                    visible: ub.hasText
                    x: 12
                    y: ub.hasChip ? uchip.y + uchip.height + 8 : 9
                    property real maxW: root.width * 0.78 - 24
                    width: Math.min(measure.implicitWidth + 2, maxW)
                    text: mText
                    readOnly: true; selectByMouse: true
                    wrapMode: TextEdit.Wrap
                    color: theme.text
                    selectionColor: theme.selection
                    font.family: theme.font; font.pixelSize: theme.fs
                    Text { id: measure; visible: false; text: mText; font: ut.font }
                }
            }
        }
    }

    Component {
        id: botMsg
        Item {
            id: bm
            width: parent ? parent.width : 0
            height: bt.height + actions.height + 8
            property bool copied: false
            TextEdit {
                id: bt
                x: 16
                width: parent.width - 34
                text: mText
                textFormat: TextEdit.MarkdownText
                readOnly: true; selectByMouse: true
                wrapMode: TextEdit.Wrap
                color: theme.body
                selectionColor: theme.selection
                font.family: theme.font; font.pixelSize: theme.fs
                onLinkActivated: function(link) { backend.openUrl(link) }
            }
            Row {
                id: actions
                x: 12
                anchors.top: bt.bottom
                anchors.topMargin: 6
                spacing: 2
                // hide actions while this message is still streaming
                // sized from the condition, not .visible: a row that isn't shown yet reports visible=false,
                // and the delegate would keep the height without the actions (next message overlaps them)
                property bool shown: !(backend.busy && mIndex === root.lastAssistant)
                visible: shown
                height: shown ? 24 : 0
                ActionIcon {
                    iconName: bm.copied ? "check" : "copy"
                    tip: tx.copy; tipItem: tooltip
                    onClicked: { backend.copyText(bt.getText(0, bt.length)); bm.copied = true; copyReset.restart() }
                }
                ActionIcon {
                    visible: mIndex === root.lastAssistant && !backend.busy
                    iconName: "retry"
                    tip: tx.retry; tipItem: tooltip
                    onClicked: backend.retry()
                }
            }
            Timer { id: copyReset; interval: 1300; onTriggered: bm.copied = false }
        }
    }

    Component {
        id: toolMsg
        Item {
            width: parent ? parent.width : 0
            height: 20
            Row {
                x: 16
                spacing: 6
                anchors.verticalCenter: parent.verticalCenter
                Image { anchors.verticalCenter: parent.verticalCenter; source: root.icon("tool"); sourceSize: Qt.size(12, 12); width: 12; height: 12; opacity: 0.55 }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    width: Math.min(implicitWidth, root.width - 60)
                    elide: Text.ElideRight
                    text: mText
                    color: theme.faint
                    font.family: theme.font; font.pixelSize: 12
                }
            }
        }
    }

    // Images are shown through backend.thumb(): a cropped copy with real rounded corners
    // (QtQuick's clip is rectangular). `probe` only reads the aspect ratio.
    Component {
        id: imageMsg
        Item {
            width: parent ? parent.width : 0
            height: frame.height
            Image { id: probe; visible: false; source: mImage; sourceSize.width: 64; asynchronous: true }
            Rectangle {
                id: frame
                x: 16
                property real ratio: probe.implicitHeight > 0 ? probe.implicitWidth / probe.implicitHeight : 1
                property real side: Math.min(240, parent.width - 34)
                width: ratio >= 1 ? side : side * ratio
                height: ratio >= 1 ? side / ratio : side
                radius: 10
                color: theme.imageBg
                Image {
                    anchors.fill: parent
                    source: probe.status === Image.Ready ? backend.thumb(mImage, Math.round(frame.width), Math.round(frame.height), 10) : ""
                    smooth: true; mipmap: true
                    asynchronous: true
                }
                Rectangle { anchors.fill: parent; radius: parent.radius; color: "transparent"; border.color: imgMa.containsMouse ? theme.outline : theme.line }
                MouseArea { id: imgMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: backend.openUrl(mImage) }
            }
        }
    }

    Component {
        id: userImageMsg
        Item {
            width: parent ? parent.width : 0
            height: uframe.height
            Image { id: uprobe; visible: false; source: mImage; sourceSize.width: 64; asynchronous: true }
            Rectangle {
                id: uframe
                anchors.right: parent.right
                anchors.rightMargin: 14
                property real ratio: uprobe.implicitHeight > 0 ? uprobe.implicitWidth / uprobe.implicitHeight : 1.6
                width: Math.min(220, root.width * 0.7, height * ratio)
                height: Math.min(150, 220 / Math.max(ratio, 0.01))
                radius: 8
                color: theme.surface
                Image {
                    anchors.fill: parent
                    source: uprobe.status === Image.Ready ? backend.thumb(mImage, Math.round(uframe.width), Math.round(uframe.height), 8) : ""
                    smooth: true; mipmap: true
                    asynchronous: true
                }
                Rectangle { anchors.fill: parent; radius: parent.radius; color: "transparent"; border.color: uMa.containsMouse ? theme.outline : theme.line }
                MouseArea { id: uMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: backend.openUrl(mImage) }
            }
        }
    }

    Component {
        id: errorMsg
        Item {
            width: parent ? parent.width : 0
            height: et.implicitHeight
            Text {
                id: et
                x: 16
                width: parent.width - 34
                wrapMode: Text.Wrap
                text: "⚠  " + mText
                color: theme.error
                font.family: theme.font; font.pixelSize: 12
            }
        }
    }
}
