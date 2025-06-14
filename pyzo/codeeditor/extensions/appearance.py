"""
Code editor extensions that change its appearance
"""

from ..qt import QtGui, QtCore, QtWidgets

Qt = QtCore.Qt

from ..misc import ce_option
from ..manager import Manager

# todo: what about calling all extensions. CE_HighlightCurrentLine,
# or EXT_HighlightcurrentLine?

from ..parsers.tokens import ParenthesisToken
import enum


class HighlightMatchingOccurrences:
    # Register style element
    _styleElements = [
        (
            "Editor.Highlight matching occurrences",
            "The background color to highlight matching occurrences of the currently selected word.",
            "back:#fdfda3",
        )
    ]

    def highlightMatchingOccurrences(self):
        """highlightMatchingOccurrences()

        Get whether to highlight matching occurrences.
        """
        return self.__highlightMatchingOccurrences

    @ce_option(True)
    def setHighlightMatchingOccurrences(self, value):
        """setHighlightMatchingOccurrences(value)

        Set whether to highlight matching occurrences.
        """
        self.__highlightMatchingOccurrences = bool(value)
        self.viewport().update()

    def _doHighlight(self, text):
        if text.strip() != text or "\u2029" in text:
            # selection has leading/trailing whitespace or contains a line break
            return

        # make cursor at the beginning of the first visible block
        cursor = self.cursorForPosition(QtCore.QPoint(0, 0))
        cursor.movePosition(cursor.MoveOperation.StartOfWord)
        doc = self.document()

        color = self.getStyleElementFormat("editor.highlightMatchingOccurrences").back
        painter = QtGui.QPainter()
        painter.begin(self.viewport())
        painter.setBrush(color)
        painter.setPen(color.darker(110))

        # flag "FindWholeWords" in doc.find would not consider "_" as a word character
        # therefore use a custom regular expression instead
        QRE = QtCore.QRegularExpression
        needle = QRE(r"\b" + QRE.escape(text) + r"\b")

        # find occurrences
        for i in range(500):
            cursor = doc.find(needle, cursor, doc.FindFlag.FindCaseSensitively)
            if cursor is None or cursor.isNull():
                # no more matches
                break

            # don't highlight the actual selection
            if cursor == self.textCursor():
                continue

            endRect = self.cursorRect(cursor)
            cursor.setPosition(min(cursor.position(), cursor.anchor()))
            startRect = self.cursorRect(cursor)

            if startRect.top() > self.height():
                # rest of document is not visible, don't bother highlighting
                break

            width = endRect.left() - startRect.left()
            cursorHeight = startRect.height()

            heightDiff = endRect.top() - startRect.top()
            if heightDiff == 0:
                painter.drawRect(startRect.left(), startRect.top(), width, cursorHeight)
            elif heightDiff > 0:
                cursor.movePosition(cursor.MoveOperation.EndOfLine)
                secondLineY = self.cursorRect(cursor).top()
                endLineY = endRect.top()
                fullLineStartX = 0
                fullLineEndX = self.width()

                # first partial line
                width = fullLineEndX - startRect.left()
                painter.drawRect(startRect.left(), startRect.top(), width, cursorHeight)

                # full lines in between
                if endLineY > secondLineY:
                    width = fullLineEndX - fullLineStartX
                    height = endLineY - secondLineY
                    painter.drawRect(fullLineStartX, secondLineY, width, height)

                # last partial line
                width = endRect.left() - fullLineStartX
                if width > 0:
                    painter.drawRect(fullLineStartX, endLineY, width, cursorHeight)

            # move to end of word again, otherwise we never advance in the doc
            cursor.movePosition(cursor.MoveOperation.EndOfWord)
        else:
            print("Matching selection highlighting did not break")

        painter.end()

    def paintEvent(self, event):
        """Paints behinds its super()."""
        cursor = self.textCursor()
        if self.__highlightMatchingOccurrences and cursor.hasSelection():
            text = cursor.selectedText()
            self._doHighlight(text)

        super().paintEvent(event)


class _ParenNotFound(Exception):
    pass


class _ParenIterator:
    """Iterates in given direction over parentheses in the document.
    Uses the stored token-list of the blocks.
    Iteration gives both a parenthesis and its global position."""

    def __init__(self, cursor, direction):
        self.cur_block = cursor.block()
        self.cur_tokens = self._getParenTokens()
        self.direction = direction
        # We need to know where we start in the current token list
        k = 0
        try:
            while self.cur_tokens[k].end != cursor.positionInBlock():
                k += 1
            self.cur_pos = k
        except IndexError:
            # If the parenthesis cannot be found, it means that it is not included
            # in any token, ie. it is part of a string or comment
            raise _ParenNotFound

    def _getParenTokens(self):
        try:
            return [
                x
                for x in self.cur_block.userData().tokens
                if isinstance(x, ParenthesisToken)
            ]
        except AttributeError:
            return []  # can be a piece of text that we do not tokenize or have not stored tokens

    def __iter__(self):
        return self

    def __next__(self):
        self.cur_pos += self.direction
        while self.cur_pos >= len(self.cur_tokens) or self.cur_pos < 0:
            if self.direction == 1:
                self.cur_block = self.cur_block.next()
            else:
                self.cur_block = self.cur_block.previous()
            if not self.cur_block.isValid():
                raise StopIteration
            self.cur_tokens = self._getParenTokens()
            if self.direction == 1:
                self.cur_pos = 0
            else:
                self.cur_pos = len(self.cur_tokens) - 1
        return (
            self.cur_tokens[self.cur_pos]._style,
            self.cur_block.position() + self.cur_tokens[self.cur_pos].end,
        )


class _PlainTextParenIterator:
    """Iterates in given direction over parentheses in the document.
    To be used when there is no parser.
    Iteration gives both a parenthesis and its global position."""

    def __init__(self, cursor, direction):
        self.fulltext = cursor.document().toPlainText()
        self.position = cursor.position() - 1
        self.direction = direction

    def __iter__(self):
        return self

    def __next__(self):
        self.position += self.direction
        try:
            while self.fulltext[self.position] not in "([{)]}":
                self.position += self.direction
                if self.position < 0:
                    raise StopIteration
        except IndexError:
            raise StopIteration
        return self.fulltext[self.position], self.position + 1


class _MatchStatus(enum.Enum):
    NoMatch = 0
    Match = 1
    MisMatch = 2


class _MatchResult:
    def __init__(self, status, corresponding=None, offending=None):
        self.status = status
        self.corresponding = corresponding
        self.offending = offending


class HighlightMatchingBracket:
    # Register style element
    _styleElements = [
        (
            "Editor.Highlight matching bracket",
            "The background color to highlight matching brackets.",
            "back:#ccc",
        ),
        (
            "Editor.Highlight unmatched bracket",
            "The background color to highlight unmatched brackets.",
            "back:#F7BE81",
        ),
        (
            "Editor.Highlight mismatching bracket",
            "The background color to highlight mismatching brackets.",
            "back:#F7819F",
        ),
    ]

    _BRACKS_OPEN = "([{"
    _BRACKS_CLOSE = ")]}"
    _BRACKS = _BRACKS_OPEN + _BRACKS_CLOSE
    _matchingBrackets = dict(
        zip(_BRACKS_OPEN + _BRACKS_CLOSE, _BRACKS_CLOSE + _BRACKS_OPEN)
    )

    def highlightMatchingBracket(self):
        """Get whether to highlight matching brackets."""
        return self.__highlightMatchingBracket

    @ce_option(True)
    def setHighlightMatchingBracket(self, value):
        """Set whether to highlight matching brackets."""
        self.__highlightMatchingBracket = bool(value)
        self.viewport().update()

    def highlightMisMatchingBracket(self):
        """Get whether to highlight mismatching brackets."""
        return self.__highlightMisMatchingBracket

    @ce_option(True)
    def setHighlightMisMatchingBracket(self, value):
        """Set whether to highlight mismatching brackets."""
        self.__highlightMisMatchingBracket = bool(value)
        self.viewport().update()

    def _highlightSingleChar(self, painter, cursor, width, colorname):
        """Draws a highlighting rectangle around the single character to the
        left of the specified cursor.
        """
        cursor_rect = self.cursorRect(cursor)
        top = cursor_rect.top()
        left = cursor_rect.left() - width
        height = cursor_rect.bottom() - top + 1
        color = self.getStyleElementFormat(colorname).back
        painter.setBrush(color)
        painter.setPen(color.darker(110))
        painter.drawRect(QtCore.QRect(int(left), int(top), int(width), int(height)))

    def _findMatchingBracket(self, char, cursor):
        """Find a bracket that matches the specified char in the specified document.
        Return a _MatchResult object indicating whether this succeded and the
        positions of the parentheses causing this result.
        """
        if char in self._BRACKS_CLOSE:
            direction = -1
            stacking = self._BRACKS_CLOSE
            unstacking = self._BRACKS_OPEN
        elif char in self._BRACKS_OPEN:
            direction = 1
            stacking = self._BRACKS_OPEN
            unstacking = self._BRACKS_CLOSE
        else:
            raise ValueError("invalid bracket character: " + char)

        stacked_paren = [(char, cursor.position())]  # using a Python list as a stack
        # stack not empty because the _ParenIterator will not give back
        # the parenthesis we're matching
        our_iterator = (
            _ParenIterator
            if self.parser() is not None and self.parser().name() != ""
            else _PlainTextParenIterator
        )
        for paren, pos in our_iterator(cursor, direction):
            if paren in stacking:
                stacked_paren.append((paren, pos))
            elif paren in unstacking:
                if self._matchingBrackets[stacked_paren[-1][0]] != paren:
                    return _MatchResult(
                        _MatchStatus.MisMatch, pos, stacked_paren[-1][1]
                    )
                else:
                    stacked_paren.pop()

            if len(stacked_paren) == 0:
                # we've found our match
                return _MatchResult(_MatchStatus.Match, pos)
        return _MatchResult(_MatchStatus.NoMatch)

    def _cursorAt(self, doc, pos):
        new_cursor = QtGui.QTextCursor(doc)
        new_cursor.setPosition(pos)
        return new_cursor

    def paintEvent(self, event):
        """Paints behinds its super().

        If the current cursor is positioned to the right of a bracket ()[]{},
        look for a matching one, and, if found, draw a highlighting rectangle
        around both brackets of the pair.
        """
        if not self.__highlightMatchingBracket:
            super().paintEvent(event)
            return

        cursor = QtGui.QTextCursor(self.textCursor())

        # We need to clear the selection because otherwise movePosition(MoveOperation.Right)
        # moves the cursor to the right end of the selection instead of advancing by one step.
        cursor.clearSelection()

        if cursor.atBlockStart():
            cursor.movePosition(cursor.MoveOperation.Right)
            movedRight = True
        else:
            movedRight = False
        text = cursor.block().text()
        pos = cursor.positionInBlock() - 1

        if len(text) > pos and len(text) > 0:
            # get the character to the left of the cursor
            char = text[pos]

            if not movedRight and char not in self._BRACKS and len(text) > pos + 1:
                # no brace to the left of cursor; try to the right
                cursor.movePosition(cursor.MoveOperation.Right)
                char = text[pos + 1]

            if char in self._BRACKS:
                doc = cursor.document()
                try:
                    match_res = self._findMatchingBracket(char, cursor)
                    fm = QtGui.QFontMetrics(doc.defaultFont())
                    width = fm.horizontalAdvance(
                        char
                    )  # assumes that both paren have the same width
                    painter = QtGui.QPainter()
                    painter.begin(self.viewport())
                    if match_res.status == _MatchStatus.NoMatch:
                        self._highlightSingleChar(
                            painter, cursor, width, "editor.highlightUnmatchedBracket"
                        )
                    elif match_res.status == _MatchStatus.Match:
                        self._highlightSingleChar(
                            painter, cursor, width, "editor.highlightMatchingBracket"
                        )
                        self._highlightSingleChar(
                            painter,
                            self._cursorAt(doc, match_res.corresponding),
                            width,
                            "editor.highlightMatchingBracket",
                        )
                    else:  # this is a mismatch
                        if (
                            cursor.position() != match_res.offending
                            or not self.highlightMisMatchingBracket()
                        ):
                            self._highlightSingleChar(
                                painter,
                                cursor,
                                width,
                                "editor.highlightUnmatchedBracket",
                            )
                        if self.highlightMisMatchingBracket():
                            self._highlightSingleChar(
                                painter,
                                self._cursorAt(doc, match_res.corresponding),
                                width,
                                "editor.highlightMisMatchingBracket",
                            )
                            self._highlightSingleChar(
                                painter,
                                self._cursorAt(doc, match_res.offending),
                                width,
                                "editor.highlightMisMatchingBracket",
                            )

                    painter.end()
                except _ParenNotFound:
                    # is raised when current parenthesis is not
                    # found in its line token list, meaning it is in a string literal
                    pass

        super().paintEvent(event)


class HighlightCurrentLine:
    """
    Highlight the current line
    """

    # Register style element
    _styleElements = [
        (
            "Editor.Highlight current line",
            "The background color of the current line highlight.",
            "back:#ffff99",
        )
    ]

    def highlightCurrentLine(self):
        """Get whether to highlight the current line."""
        return self.__highlightCurrentLine

    @ce_option(True)
    def setHighlightCurrentLine(self, value):
        """Set whether to highlight the current line."""
        self.__highlightCurrentLine = bool(value)
        self.viewport().update()

    def paintEvent(self, event):
        """Paints behind its super()

        Paints a rectangle spanning the current block (in case of line wrapping, this
        means multiple lines)
        """
        if not self.highlightCurrentLine():
            super().paintEvent(event)
            return

        # Get color
        color = self.getStyleElementFormat("editor.highlightCurrentLine").back

        # Find the top of the current block, and the height
        cursor = self.textCursor()
        cursor.movePosition(cursor.MoveOperation.StartOfBlock)
        top = self.cursorRect(cursor).top()
        cursor.movePosition(cursor.MoveOperation.EndOfBlock)
        height = self.cursorRect(cursor).bottom() - top + 1

        margin = self.document().documentMargin()
        painter = QtGui.QPainter()
        painter.begin(self.viewport())
        painter.fillRect(
            QtCore.QRect(
                int(margin),
                int(top),
                int(self.viewport().width() - 2 * margin),
                int(height),
            ),
            color,
        )
        painter.end()

        super().paintEvent(event)

        # for debugging paint events
        # if 'log' not in self.__class__.__name__.lower():
        #    print(height, event.rect().width())


class IndentationGuides:
    # Register style element
    _styleElements = [
        (
            "Editor.Indentation guides",
            "The color and style of the indentation guides.",
            "fore:#DDF,linestyle:solid",
        )
    ]

    def showIndentationGuides(self):
        """Get whether to show indentation guides."""
        return self.__showIndentationGuides

    @ce_option(True)
    def setShowIndentationGuides(self, value):
        """Set whether to show indentation guides."""
        self.__showIndentationGuides = bool(value)
        self.viewport().update()

    def paintEvent(self, event):
        """Paint the indentation guides, using the indentation info calculated
        by the highlighter.
        """
        super().paintEvent(event)

        if not self.showIndentationGuides():
            return

        # Get doc and viewport
        doc = self.document()
        viewport = self.viewport()

        # Get multiplication factor and indent width
        indentWidth = self.indentWidth()
        if self.indentUsingSpaces():
            factor = 1
        else:
            factor = indentWidth

        # Init painter
        painter = QtGui.QPainter()
        painter.begin(viewport)

        # Prepare pen
        format = self.getStyleElementFormat("editor.IndentationGuides")
        pen = QtGui.QPen(format.fore)
        pen.setStyle(format.linestyle)
        painter.setPen(pen)
        offset = doc.documentMargin() + self.contentOffset().x()

        def paintIndentationGuides(cursor):
            y3 = self.cursorRect(cursor).top()
            y4 = self.cursorRect(cursor).bottom()

            bd = cursor.block().userData()
            if bd and hasattr(bd, "indentation") and bd.indentation:
                for x in range(indentWidth, bd.indentation * factor, indentWidth):
                    w = self.fontMetrics().horizontalAdvance("i" * x) + offset
                    w += 1  # Put it more under the block
                    if w > 0:  # if scrolled horizontally it can become < 0
                        painter.drawLine(QtCore.QLine(int(w), int(y3), int(w), int(y4)))

        self.doForVisibleBlocks(paintIndentationGuides)

        # Done
        painter.end()


class FullUnderlines:
    def paintEvent(self, event):
        """Paint a horizontal line for the blocks for which there is a
        syntax format that has underline:full. Whether this is the case
        is stored at the blocks user data.
        """
        super().paintEvent(event)

        painter = QtGui.QPainter()
        painter.begin(self.viewport())

        margin = self.document().documentMargin()
        w = self.viewport().width()

        def paintUnderline(cursor):
            y = self.cursorRect(cursor).bottom()
            fullUnderlineFormat = getattr(
                cursor.block().userData(), "fullUnderlineFormat", None
            )
            if fullUnderlineFormat is not None:
                # Apply pen
                pen = QtGui.QPen(fullUnderlineFormat.fore)
                pen.setStyle(fullUnderlineFormat.linestyle)
                painter.setPen(pen)
                # Paint
                painter.drawLine(
                    QtCore.QLine(int(margin), int(y), int(w - 2 * margin), int(y))
                )

        self.doForVisibleBlocks(paintUnderline)

        painter.end()


class CodeFolding:
    def paintEvent(self, event):
        super().paintEvent(event)

        return  # Code folding code is not yet complete

        painter = QtGui.QPainter()
        painter.begin(self.viewport())

        margin = int(self.document().documentMargin())

        def paintCodeFolders(cursor):
            y = int(self.cursorRect(cursor).top())
            h = int(self.cursorRect(cursor).height())
            rect = QtCore.QRect(margin, y, h, h)
            text = cursor.block().text()
            if text.rstrip().endswith(":"):
                painter.drawRect(rect)
                AF = QtCore.Qt.AlignmentFlag
                painter.drawText(rect, AF.AlignVCenter | AF.AlignHCenter, "-")
                # Apply pen

                # Paint
                # painter.drawLine(QtCore.QLine(int(margin), int(y), int(w - 2*margin), int(y)))

        self.doForVisibleBlocks(paintCodeFolders)

        painter.end()


class LongLineIndicator:
    # Register style element
    _styleElements = [
        (
            "Editor.Long line indicator",
            "The color and style of the long line indicator.",
            "fore:#BBB,linestyle:solid",
        )
    ]

    def longLineIndicatorPosition(self):
        """Get the position of the long line indicator (aka edge column).
        A value of 0 or smaller means that no indicator is shown.
        """
        return self.__longLineIndicatorPosition

    @ce_option(80)
    def setLongLineIndicatorPosition(self, value):
        """Set the position of the long line indicator (aka edge column).
        A value of 0 or smaller means that no indicator is shown.
        """
        self.__longLineIndicatorPosition = int(value)
        self.viewport().update()

    def paintEvent(self, event):
        """Paint the long line indicator. Paints behind its super()"""
        if self.longLineIndicatorPosition() <= 0:
            super().paintEvent(event)
            return

        # Get doc and viewport
        doc = self.document()
        viewport = self.viewport()

        # Get position of long line
        fm = self.fontMetrics()
        # horizontalAdvance of ('i'*length) not length * (horizontalAdvance of 'i') b/c of
        # font kerning and rounding
        x = fm.horizontalAdvance("i" * self.longLineIndicatorPosition())
        x += doc.documentMargin() + self.contentOffset().x()
        x += 1  # Move it a little next to the cursor

        # Prepare painter
        painter = QtGui.QPainter()
        painter.begin(viewport)

        # Prepare pen
        format = self.getStyleElementFormat("editor.LongLineIndicator")
        pen = QtGui.QPen(format.fore)
        pen.setStyle(format.linestyle)
        painter.setPen(pen)

        # Draw line and end painter
        painter.drawLine(QtCore.QLine(int(x), 0, int(x), int(viewport.height())))
        painter.end()

        # Propagate event
        super().paintEvent(event)


class ShowWhitespace:
    def showWhitespace(self):
        """Show or hide whitespace markers"""
        option = self.document().defaultTextOption()
        return bool(option.flags() & option.ShowTabsAndSpaces)

    @ce_option(False)
    def setShowWhitespace(self, value):
        try:
            option = self.document().defaultTextOption()
            if value:
                option.setFlags(option.flags() | option.Flag.ShowTabsAndSpaces)
            else:
                option.setFlags(option.flags() & ~option.Flag.ShowTabsAndSpaces)
            self.document().setDefaultTextOption(option)
        except Exception:
            # This can produce: 2147483617 is not a valid QTextOption.Flag
            # and I do not know how to avoid it :/
            pass


class ShowLineEndings:
    @ce_option(False)
    def showLineEndings(self):
        """Get whether line ending markers are shown."""
        option = self.document().defaultTextOption()
        return bool(option.flags() & option.ShowLineAndParagraphSeparators)

    def setShowLineEndings(self, value):
        try:
            option = self.document().defaultTextOption()
            if value:
                option.setFlags(
                    option.flags() | option.Flag.ShowLineAndParagraphSeparators
                )
            else:
                option.setFlags(
                    option.flags() & ~option.Flag.ShowLineAndParagraphSeparators
                )
            self.document().setDefaultTextOption(option)
        except Exception:
            # This can produce: 2147483617 is not a valid QTextOption.Flag
            # and I do not know how to avoid it :/
            pass


class LineNumbers:
    # Margin on both side of the line numbers
    _LineNumberAreaMargin = 3

    # Register style element
    _styleElements = [
        (
            "Editor.Line numbers",
            "The text- and background-color of the line numbers.",
            "fore:#222,back:#DDD",
        )
    ]

    class __LineNumberArea(QtWidgets.QWidget):
        """This is the widget reponsible for drawing the line numbers."""

        def __init__(self, codeEditor):
            super().__init__(codeEditor)
            self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
            self._pressedY = None
            self._lineNrChoser = None

        def _getY(self, pos):
            tmp = self.mapToGlobal(pos)
            return self.parent().viewport().mapFromGlobal(tmp).y()

        def mousePressEvent(self, event):
            self._pressedY = self._getY(event.position().toPoint())

        def mouseReleaseEvent(self, event):
            self._handleWholeBlockSelection(self._getY(event.position().toPoint()))

        def mouseMoveEvent(self, event):
            self._handleWholeBlockSelection(self._getY(event.position().toPoint()))

        def _handleWholeBlockSelection(self, y2):
            # Get y1 and sort (y1, y2)
            y1 = self._pressedY
            if y1 is None:
                y1 = y2
            if y2 < y1:
                y1, y2 = y2, y1

            # Get cursor and two cursors corresponding to selected blocks
            editor = self.parent()
            cursor = editor.textCursor()
            c1 = editor.cursorForPosition(QtCore.QPoint(0, int(y1)))
            c2 = editor.cursorForPosition(QtCore.QPoint(0, int(y2)))

            # Make these two cursors select the whole block
            c1.movePosition(c1.MoveOperation.StartOfBlock, c1.MoveMode.MoveAnchor)
            c2.movePosition(c2.MoveOperation.EndOfBlock, c2.MoveMode.MoveAnchor)

            # Apply selection
            cursor.setPosition(c1.position(), cursor.MoveMode.MoveAnchor)
            cursor.setPosition(c2.position(), cursor.MoveMode.KeepAnchor)
            editor.setTextCursor(cursor)

        def mouseDoubleClickEvent(self, event):
            self.showLineNumberChoser()

        def showLineNumberChoser(self):
            # Create line number choser if needed
            if self._lineNrChoser is None:
                self._lineNrChoser = LineNumbers.LineNumberChoser(self.parent())
            # Get editor and cursor
            editor = self.parent()
            cursor = editor.textCursor()
            # Get (x,y) pos and apply
            x, y = self.width() + 4, editor.cursorRect(cursor).y()
            self._lineNrChoser.move(int(x), int(y))
            # Show/reset line number choser
            self._lineNrChoser.reset(cursor.blockNumber() + 1)

        def paintEvent(self, event):
            editor = self.parent()

            if not editor.showLineNumbers():
                return

            # Get doc and viewport
            viewport = editor.viewport()

            # Get format and margin
            format = editor.getStyleElementFormat("editor.LineNumbers")
            margin = editor._LineNumberAreaMargin

            # Init painter
            painter = QtGui.QPainter()
            painter.begin(self)

            # Get which part to paint. Just do all to avoid glitches
            w = editor._getLineNumberAreaWidth()
            y1, y2 = 0, editor.height()
            # y1, y2 = event.rect().top()-10, event.rect().bottom()+10

            # Get offset
            tmp = self.mapToGlobal(QtCore.QPoint(0, 0))
            offset = viewport.mapFromGlobal(tmp).y()

            # Draw the background
            painter.fillRect(QtCore.QRect(0, int(y1), int(w), int(y2)), format.back)

            # Get cursor
            cursor = editor.cursorForPosition(QtCore.QPoint(0, int(y1)))

            # Prepare fonts
            font1 = editor.font()
            font2 = editor.font()
            font2.setBold(True)
            currentBlockNumber = editor.textCursor().block().blockNumber()

            # Init painter with font and color
            painter.setFont(font1)
            painter.setPen(format.fore)

            # Repainting always starts at the first block in the viewport,
            # regardless of the event.rect().y(). Just to keep it simple
            while True:
                blockNumber = cursor.block().blockNumber()

                y = editor.cursorRect(cursor).y()

                # Set font to bold if line number is the current
                if blockNumber == currentBlockNumber:
                    painter.setFont(font2)

                AF = Qt.AlignmentFlag
                painter.drawText(
                    0, y - offset, w - margin, 50, AF.AlignRight, str(blockNumber + 1)
                )

                # Set font back
                if blockNumber == currentBlockNumber:
                    painter.setFont(font1)

                if y > y2:
                    break  # Reached end of the repaint area
                if not cursor.block().next().isValid():
                    break  # Reached end of the text

                cursor.movePosition(cursor.MoveOperation.NextBlock)

            # Done
            painter.end()

    class LineNumberChoser(QtWidgets.QSpinBox):
        def __init__(self, parent):
            super().__init__(parent)
            self._editor = parent

            ss = (
                "QSpinBox { border: 2px solid #789; border-radius: 3px; padding: 4px; }"
            )
            self.setStyleSheet(ss)

            self.setPrefix("Go to line: ")
            self.setAccelerated(True)
            self.setButtonSymbols(self.ButtonSymbols.NoButtons)
            self.setCorrectionMode(self.CorrectionMode.CorrectToNearestValue)

            # Signal for when value changes, and flag to disable it once
            self._ignoreSignalOnceFlag = False
            self.valueChanged.connect(self.onValueChanged)

        def reset(self, currentLineNumber):
            # Set value to (given) current line number
            self._ignoreSignalOnceFlag = True
            self.setRange(1, self._editor.blockCount())
            self.setValue(currentLineNumber)
            # Select text and focus so that the user can simply start typing
            self.selectAll()
            self.setFocus()
            # Make visible
            self.show()
            self.raise_()

        def focusOutEvent(self, event):
            self.hide()

        def keyPressEvent(self, event):
            if event.key() in [
                QtCore.Qt.Key.Key_Escape,
                QtCore.Qt.Key.Key_Enter,
                QtCore.Qt.Key.Key_Return,
            ]:
                self._editor.setFocus()  # Moves focus away, thus hiding self
            else:
                super().keyPressEvent(event)

        def onValueChanged(self, nr):
            if self._ignoreSignalOnceFlag:
                self._ignoreSignalOnceFlag = False
            else:
                self._editor.gotoLine(nr)

    def __init__(self, *args, **kwds):
        self.__lineNumberArea = None
        self.__leftMarginHandle = None
        super().__init__(*args, **kwds)
        # Create widget that draws the line numbers
        self.__lineNumberArea = self.__LineNumberArea(self)
        # Issue an update when the font or amount of line numbers changes
        self.blockCountChanged.connect(self.__onBlockCountChanged)
        self.fontChanged.connect(self.__onBlockCountChanged)
        self.__leftMarginHandle = self._setLeftBarMargin(
            self.__leftMarginHandle, self._getLineNumberAreaWidth()
        )
        self.__onBlockCountChanged()

    def gotoLinePopup(self):
        """Popup the little widget to quickly goto a certain line.
        Can also be achieved by double-clicking the line number area.
        """
        self.__lineNumberArea.showLineNumberChoser()

    def showLineNumbers(self):
        return self.__showLineNumbers

    @ce_option(True)
    def setShowLineNumbers(self, value):
        self.__showLineNumbers = bool(value)
        # Note that this method is called before the __init__ is finished,
        # so that the __lineNumberArea is not yet created.
        if self.__lineNumberArea:
            if self.__showLineNumbers:
                self.__lineNumberArea.show()
            else:
                self.__lineNumberArea.hide()
            if self.__leftMarginHandle is not None:
                self._setLeftBarMargin(
                    self.__leftMarginHandle, self._getLineNumberAreaWidth()
                )

    def _getLineNumberAreaWidth(self):
        """Count the number of lines, compute the length of the longest line number
        (in pixels)
        """
        if not self.__showLineNumbers:
            return 0
        lastLineNumber = self.blockCount()
        margin = self._LineNumberAreaMargin
        return self.fontMetrics().horizontalAdvance(str(lastLineNumber)) + 2 * margin

    def __onBlockCountChanged(self, count=None):
        """Update the line number area width. This requires to set the
        viewport margins, so there is space to draw the linenumber area
        """
        if self.__showLineNumbers:
            self.__leftMarginHandle = self._setLeftBarMargin(
                self.__leftMarginHandle, self._getLineNumberAreaWidth()
            )

    def resizeEvent(self, event):
        super().resizeEvent(event)

        # On resize, resize the lineNumberArea, too
        rect = self.contentsRect()
        m = self._getMarginBeforeLeftBar(self.__leftMarginHandle)
        w = self._getLineNumberAreaWidth()
        self.__lineNumberArea.setGeometry(rect.x() + m, rect.y(), w, rect.height())

    def paintEvent(self, event):
        super().paintEvent(event)
        # On repaint, update the complete line number area
        w = self._getLineNumberAreaWidth()
        self.__lineNumberArea.update(0, 0, w, self.height())


class BreakPoints:
    # Register style element
    _styleElements = [
        (
            "Editor.BreakPoints",
            "The fore- and background-color of the breakpoints.",
            "fore:#F66,back:#dfdfe1",
        )
    ]

    class __BreakPointArea(QtWidgets.QWidget):
        """This is the widget reponsible for drawing the break points."""

        def __init__(self, codeEditor):
            super().__init__(codeEditor)
            self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
            self.setMouseTracking(True)
            self._virtualBreakpoint = 0

        def _getY(self, pos):
            tmp = self.mapToGlobal(pos)
            return self.parent().viewport().mapFromGlobal(tmp).y()

        def mousePressEvent(self, event):
            self._toggleBreakPoint(self._getY(event.position().toPoint()))

        def mouseMoveEvent(self, event):
            y = self._getY(event.position().toPoint())
            editor = self.parent()
            c1 = editor.cursorForPosition(QtCore.QPoint(0, int(y)))
            self._virtualBreakpoint = c1.blockNumber() + 1
            self.update()

        def leaveEvent(self, event):
            self._virtualBreakpoint = 0
            self.update()

        def _toggleBreakPoint(self, y):
            # Get breakpoint corresponding to pressed pos
            editor = self.parent()
            c1 = editor.cursorForPosition(QtCore.QPoint(0, int(y)))
            linenr = c1.blockNumber() + 1
            # Toggle
            self.parent().toggleBreakpoint(linenr)

        def paintEvent(self, event):
            editor = self.parent()

            if not editor.showBreakPoints():
                return

            # Get format and margin
            format = editor.getStyleElementFormat("editor.breakpoints")
            w = editor._breakPointWidth
            marginX = max(1, int(0.1 * w))
            bulletWidth = w - 2 * marginX

            # Init painter
            painter = QtGui.QPainter()
            painter.begin(self)

            # Get which part to paint. Just do all to avoid glitches
            y1, y2 = 0, editor.height()

            # Draw the background
            painter.fillRect(QtCore.QRect(0, int(y1), int(w), int(y2)), format.back)

            # Get debug indicator and list of sorted breakpoints
            debugBlockIndicator = editor._debugLineIndicator - 1
            virtualBreakpoint = self._virtualBreakpoint - 1
            breakpoints = self.parent()._breakPoints
            if not (
                len(breakpoints) > 0
                or editor._debugLineIndicator
                or editor._debugLineIndicators
                or virtualBreakpoint > 0
            ):
                return

            # Get cursor
            cursor = editor.cursorForPosition(QtCore.QPoint(0, int(y1)))

            # Get start block number and bullet offset in pixels
            startBlockNumber = cursor.block().blockNumber()
            marginY = int(0.5 * (editor.cursorRect(cursor).height() - bulletWidth))
            bulletOffset = editor.contentOffset().y() + marginY
            # Prepare painter
            painter.setPen(QtGui.QColor("#777"))
            painter.setBrush(format.fore)
            painter.setRenderHint(painter.RenderHint.Antialiasing)

            # Draw breakpoints
            for linenr, (enabled, *_) in sorted(breakpoints.items()):
                blockNumber = linenr - 1
                if blockNumber < startBlockNumber:
                    continue
                # Get block
                block = editor.document().findBlockByNumber(blockNumber)
                if block.isValid():
                    y = editor.blockBoundingGeometry(block).y() + bulletOffset
                    if enabled:
                        painter.drawEllipse(
                            marginX, int(y), int(bulletWidth), int(bulletWidth)
                        )
                    else:
                        painter.drawPie(
                            marginX,
                            int(y),
                            int(bulletWidth),
                            int(bulletWidth),
                            90 * 16,
                            180 * 16,
                        )

            # Draw *the* debug marker
            if debugBlockIndicator >= 0:
                painter.setBrush(QtGui.QColor("#6F6"))
                # Get block
                block = editor.document().findBlockByNumber(debugBlockIndicator)
                if block.isValid():
                    y = editor.blockBoundingGeometry(block).y() + bulletOffset
                    y += 0.25 * bulletWidth
                    painter.drawEllipse(
                        marginX, int(y), int(bulletWidth), int(0.5 * bulletWidth)
                    )

            # Draw other debug markers
            for debugLineIndicator in editor._debugLineIndicators:
                debugBlockIndicator = debugLineIndicator - 1
                painter.setBrush(QtGui.QColor("#DDD"))
                # Get block
                block = editor.document().findBlockByNumber(debugBlockIndicator)
                if block.isValid():
                    y = editor.blockBoundingGeometry(block).y() + bulletOffset
                    y += 0.25 * bulletWidth
                    painter.drawEllipse(
                        marginX, int(y), int(bulletWidth), int(0.5 * bulletWidth)
                    )

            # Draw virtual break point
            if virtualBreakpoint > 0:
                painter.setBrush(QtGui.QColor(0, 0, 0, 0))
                # Get block
                block = editor.document().findBlockByNumber(virtualBreakpoint)
                if block.isValid():
                    y = editor.blockBoundingGeometry(block).y() + bulletOffset
                    painter.drawEllipse(
                        marginX, int(y), int(bulletWidth), int(bulletWidth)
                    )

            # Done
            painter.end()

    def __init__(self, *args, **kwds):
        self.__breakPointArea = None
        self.__leftMarginHandle = None
        super().__init__(*args, **kwds)
        # Create widget that draws the breakpoints
        self._updateBreakPointWidth()
        self.__breakPointArea = self.__BreakPointArea(self)
        self.__leftMarginHandle = self._setLeftBarMargin(
            self.__leftMarginHandle, self._getBreakPointAreaWidth()
        )
        self._breakPoints = {}  # int -> enabled, block, blockPrev, blockNext
        self._debugLineIndicator = 0
        self._debugLineIndicators = set()
        self.blockCountChanged.connect(self.__onBlockCountChanged)

    def __onBlockCountChanged(self):
        """Track breakpoints so we can update the number when text is inserted
        above.
        """
        newBreakPoints = {}
        breakPointDeleted = False

        for linenr in list(self._breakPoints):
            enabled, block, block_previous, block_next = self._breakPoints[linenr]

            # Apparently there is a bug in Qt5 and Qt6 that can cause a segmentation fault.
            # When there is a faulty block "block.previous()", calling methods such as
            # "block.previous().blockNumber()" will crash Pyzo immediately.
            # These crashes happend sometimes after Qt re-created a block and we still
            # have the outdated block reference in our self._breakPoints dictionary.
            # Such a block re-creation will happen for example during undo operations, but
            # also when a block is merged with a previous empty one (by pressing backspace
            # at the beginning of a line below an empty line).
            # See https://github.com/pyzo/pyzo/pull/949
            #
            # So, to avoid crashes, we discard breakpoints that had their block re-created.
            # To detect if the block was re-created, we check if its userData was reset
            # to None. When adding a block to "self._breakPoints", we make sure it has
            # userData set to something different than None.
            #
            # According to the Qt docs from https://doc.qt.io/qt-6/qtextblock.html:
            # "The user data object is not stored in the undo history, so it will not be
            # available after undoing the deletion of a text block."

            if block.userData() is None:
                # The block assigned to the breakpoint was re-created by Qt after we
                # added it to the self._breakPoints dict.
                # To avoid a crash we delete the breakpoint.
                del self._breakPoints[linenr]
                breakPointDeleted = True
                continue

            block_linenr = block.blockNumber() + 1
            prev_ok = block.previous().blockNumber() == block_previous.blockNumber()
            next_ok = block.next().blockNumber() == block_next.blockNumber()

            if prev_ok or next_ok:
                if block_linenr == linenr:
                    if prev_ok and next_ok:
                        pass  # All is well
                    else:
                        # Update refs
                        self._breakPoints[linenr] = (
                            enabled,
                            block,
                            block.previous(),
                            block.next(),
                        )
                else:
                    # Update linenr -- this is the only case where we "move" the breakpoint
                    newBreakPoints[block_linenr] = self._breakPoints.pop(linenr)
                    breakPointDeleted = True
            else:
                if block_linenr == linenr:
                    # Just update refs
                    self._breakPoints[linenr] = (
                        enabled,
                        block,
                        block.previous(),
                        block.next(),
                    )
                else:
                    # unexpected --> delete breakpoint
                    del self._breakPoints[linenr]
                    breakPointDeleted = True

        if newBreakPoints or breakPointDeleted:
            self._breakPoints.update(newBreakPoints)
            self.breakPointsChanged.emit(self)
            self.__breakPointArea.update()

    def breakPoints(self, triState=False):
        """A list of breakpoints for this editor."""
        if triState:
            return sorted(
                (linenr, enabled) for linenr, (enabled, *_) in self._breakPoints.items()
            )
        else:
            return sorted(
                linenr for linenr, (enabled, *_) in self._breakPoints.items() if enabled
            )

    def clearBreakPoints(self):
        """Remove all breakpoints for this editor."""
        for linenr in self.breakPoints():
            self.toggleBreakpoint(linenr, triState=False)

    def toggleBreakpoint(self, linenr=None, triState=True):
        """Turn breakpoint on / half (disabled) / off (removed) for given linenr of current line."""
        if linenr is None:
            linenr = self.textCursor().blockNumber() + 1

        if linenr in self._breakPoints:
            enabled, b, bPrev, bNext = self._breakPoints.pop(linenr)
            if triState and enabled:
                enabled = False
            else:
                b = None  # indicate to not add a new modified breakpoint
        else:
            enabled = True
            c = self.textCursor()
            c.movePosition(c.MoveOperation.Start)
            c.movePosition(c.MoveOperation.NextBlock, c.MoveMode.MoveAnchor, linenr - 1)
            b = c.block()
            bPrev = b.previous()
            bNext = b.next()

        if b is not None:
            # As described in method "__onBlockCountChanged", we want to make sure that
            # the userData of the block is set to anything but None. It is totally ok that
            # other Pyzo modules such as the highlighter will overwrite that userData as
            # long as it is not set back to None.
            if b.userData() is None:
                b.setUserData(
                    QtGui.QTextBlockUserData()
                )  # just something other than None

            self._breakPoints[linenr] = enabled, b, bPrev, bNext

        self.breakPointsChanged.emit(self)
        self.__breakPointArea.update()

    def jumpPreviousBreakpoint(self):
        currentLinenr = self.textCursor().blockNumber() + 1
        newLinenr = max(
            (linenr for linenr in self._breakPoints if linenr < currentLinenr),
            default=None,
        )
        if newLinenr is not None:
            self.gotoLine(newLinenr, keepHorizontalPos=True)

    def jumpNextBreakpoint(self):
        currentLinenr = self.textCursor().blockNumber() + 1
        newLinenr = min(
            (linenr for linenr in self._breakPoints if linenr > currentLinenr),
            default=None,
        )
        if newLinenr is not None:
            self.gotoLine(newLinenr, keepHorizontalPos=True)

    def setDebugLineIndicator(self, linenr, active=True):
        """Set the debug line indicator to the given line number.
        If None or 0, the indicator is hidden.
        """
        linenr = int(linenr or 0)
        if not linenr:
            # Remove all indicators
            if self._debugLineIndicator or self._debugLineIndicators:
                self._debugLineIndicator = 0
                self._debugLineIndicators = set()
                self.__breakPointArea.update()
        elif active:
            # Set *the* indicator
            if linenr != self._debugLineIndicator:
                self._debugLineIndicators.discard(linenr)
                self._debugLineIndicator = linenr
                self.__breakPointArea.update()
        else:
            # Add to set of indicators
            if linenr not in self._debugLineIndicators:
                self._debugLineIndicators.add(linenr)
                self.__breakPointArea.update()

    def _getBreakPointAreaWidth(self):
        if not self.__showBreakPoints:
            return 0
        else:
            return self._breakPointWidth

    def showBreakPoints(self):
        return self.__showBreakPoints

    @ce_option(True)
    def setShowBreakPoints(self, value):
        self.__showBreakPoints = bool(value)
        # Note that this method is called before the __init__ is finished,
        # so that the area is not yet created.
        self._updateBreakPointWidth()
        if self.__breakPointArea:
            if self.__showBreakPoints:
                self.__breakPointArea.show()
            else:
                self.__breakPointArea.hide()
                self.clearBreakPoints()
        if self.__leftMarginHandle is not None:
            self._setLeftBarMargin(
                self.__leftMarginHandle, self._getBreakPointAreaWidth()
            )

    def _updateBreakPointWidth(self):
        """set width of breakpoint bar (actual points are smaller)"""
        self._breakPointWidth = round(0.8 * self.cursorRect(self.textCursor()).height())

    def resizeEvent(self, event):
        super().resizeEvent(event)

        # On resize, resize the breakpointArea, too
        self._updateBreakPointWidth()
        rect = self.contentsRect()
        m = self._getMarginBeforeLeftBar(self.__leftMarginHandle)
        w = self._getBreakPointAreaWidth()
        self.__breakPointArea.setGeometry(rect.x() + m, rect.y(), w, rect.height())
        self.__leftMarginHandle = self._setLeftBarMargin(
            self.__leftMarginHandle, self._getBreakPointAreaWidth()
        )

    def paintEvent(self, event):
        super().paintEvent(event)
        # On repaint, update the complete breakPointArea
        w = self._getBreakPointAreaWidth()
        self.__breakPointArea.update(0, 0, w, self.height())


class Wrap:
    def wrap(self):
        """Enable or disable wrapping"""
        option = self.document().defaultTextOption()
        return not bool(option.wrapMode() == option.WrapMode.NoWrap)

    @ce_option(True)
    def setWrap(self, value):
        option = self.document().defaultTextOption()
        if value:
            option.setWrapMode(option.WrapMode.WrapAtWordBoundaryOrAnywhere)
        else:
            option.setWrapMode(option.WrapMode.NoWrap)
        self.document().setDefaultTextOption(option)


# todo: move this bit to base class?
# This functionality embedded in the highlighter and even has a designated
# subpackage. I feel that it should be a part of the base editor.
# Note: if we do this, remove the hasattr call in the highlighter.
class SyntaxHighlighting:
    """Notes on syntax highlighting.

    The syntax highlighting/parsing is performed using three "components".

    The base component are the token instances. Each token simply represents
    a row of characters in the text the belong to each-other and should
    be styled in the same way. There is a token class for each particular
    "thing" in the code, such as comments, strings, keywords, etc. Some
    tokens are specific to a particular language.

    There is a function that produces a set of tokens, when given a line of
    text and a state parameter. There is such a function for each language.
    These "parsers" are defined in the parsers subpackage.

    And lastly, there is the Highlighter class, that applies the parser function
    to obtain the set of tokens and using the names of these tokens applies
    styling. The styling can be defined by giving a dict that maps token names
    to style representations.

    """

    # Register all syntax style elements
    _styleElements = Manager.getStyleElementDescriptionsForAllParsers()

    def parser(self):
        """Get the parser instance currently in use to parse the code for
        syntax highlighting and source structure. Can be None.
        """
        try:
            return self.__parser
        except AttributeError:
            return None

    @ce_option(None)
    def setParser(self, parserName=""):
        """Set the current parser by giving the parser name."""
        # Set parser
        self.__parser = Manager.getParserByName(parserName)

        # Restyle, use setStyle for lazy updating
        self.setStyle()
