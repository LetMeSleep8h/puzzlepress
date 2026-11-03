import { useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties } from 'react';
import {
  blockText,
  clampPos,
  clearFormatting,
  collapsed,
  deleteBackward,
  deleteForward,
  deleteRange,
  faceIsBold,
  faceIsItalic,
  familyOf,
  fromPlain,
  hasMark,
  insertLineBreak,
  insertText,
  isRich,
  normalize,
  ordered,
  setBlocks,
  sharedStyle,
  splitBlock,
  stored,
  styleAt,
  styleRange,
  toggleMark,
  variantAvailable,
  wordBoundary,
  type Mark,
  type Pos,
  type RichBlock,
  type RichDoc,
  type RunStyle,
  type Sel,
} from './rich-text-model';

// A compact rich text editor for cover text boxes and the back-cover text. The
// document is Python's structured rich text (never HTML): every edit goes through
// the pure model in rich-text-model.ts and the browser only shows the result.
// While nothing is formatted the field stays plain text; Python lays out and
// renders the real type, so this view approximates faces and sizes on screen.

const FAMILY_LABELS: Record<string, string> = {
  sans: 'Vera Sans',
  serif: 'Newsreader',
  'serif-display': 'Newsreader Display',
};
const SCREEN_FAMILY: Record<string, string> = {
  sans: "'Public Sans Variable', sans-serif",
  serif: "'Newsreader Variable', serif",
  'serif-display': "'Newsreader Variable', serif",
};
const MOD =
  typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform)
    ? 'Meta'
    : 'Control';

function textNodes(root: Node): Text[] {
  const nodes: Text[] = [];
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  for (let node = walker.nextNode(); node; node = walker.nextNode()) nodes.push(node as Text);
  return nodes;
}

function blockOf(node: Node | null): HTMLElement | null {
  let current: Node | null = node;
  while (current && !(current instanceof HTMLElement && current.dataset.block !== undefined))
    current = current.parentNode;
  return current as HTMLElement | null;
}

function domToPos(root: HTMLElement, node: Node, offset: number): Pos | null {
  if (node === root) {
    const index = Math.min(offset, root.children.length - 1);
    const child = root.children[index] as HTMLElement | undefined;
    if (!child) return null;
    const block = Number(child.dataset.block);
    return offset >= root.children.length
      ? { block, offset: (child.textContent ?? '').length }
      : { block, offset: 0 };
  }
  const element = blockOf(node);
  if (!element || !root.contains(element)) return null;
  const range = document.createRange();
  range.setStart(element, 0);
  range.setEnd(node, offset);
  return { block: Number(element.dataset.block), offset: range.toString().length };
}

function posToDom(root: HTMLElement, pos: Pos): [Node, number] | null {
  const element = root.querySelector<HTMLElement>(`[data-block="${pos.block}"]`);
  if (!element) return null;
  let remaining = pos.offset;
  const nodes = textNodes(element);
  for (const text of nodes) {
    if (remaining <= text.data.length) return [text, remaining];
    remaining -= text.data.length;
  }
  const last = nodes.at(-1);
  return last ? [last, last.data.length] : [element, 0];
}

function runCss(style: RunStyle, base: { family: string; bold: boolean; italic: boolean }) {
  const family = style.font ?? base.family;
  const css: CSSProperties = {
    fontWeight: (style.bold ?? base.bold) ? 700 : 400,
    fontStyle: (style.italic ?? base.italic) ? 'italic' : 'normal',
    fontFamily: SCREEN_FAMILY[family] ?? 'inherit',
  };
  if (style.underline) css.textDecoration = 'underline';
  if (style.size) css.fontSize = `${Math.min(36, Math.max(9, style.size * 0.75))}px`;
  if (style.color) css.color = style.color;
  return css;
}

export function RichTextEditor({
  id,
  label,
  hint,
  value,
  onChange,
  baseFace,
  fonts,
  invalid,
  disabled,
  maxLength,
}: {
  id: string;
  label: string;
  hint?: string;
  value: string | RichDoc;
  onChange: (value: string | RichDoc) => void;
  baseFace?: string;
  fonts: [string, string][]; // Imported font ids and their names.
  invalid?: boolean;
  disabled?: boolean;
  maxLength: number;
}) {
  const doc = useMemo(() => (isRich(value) ? normalize(value) : fromPlain(value ?? '')), [value]);
  const root = useRef<HTMLDivElement>(null);
  const docRef = useRef(doc);
  docRef.current = doc;
  const [sel, setSel] = useState<Sel>({
    anchor: { block: 0, offset: 0 },
    focus: { block: 0, offset: 0 },
  });
  const selRef = useRef(sel);
  const restore = useRef<Sel | null>(null);
  const [pending, setPending] = useState<RunStyle | null>(null);
  const composing = useRef<Sel | null>(null);
  const [renderKey, setRenderKey] = useState(0);
  const [notice, setNotice] = useState('');
  const base = {
    family: familyOf(baseFace),
    bold: faceIsBold(baseFace),
    italic: faceIsItalic(baseFace),
  };

  const commit = (next: RichDoc, caret: Pos | Sel, nextPending: RunStyle | null = null) => {
    const normal = normalize(next);
    const text = normal.blocks.map(blockText).join('\n');
    if (text.length > maxLength) {
      setNotice(`This text is limited to ${maxLength} characters.`);
      return;
    }
    setNotice('');
    const nextSel = 'block' in caret ? { anchor: caret, focus: caret } : caret;
    restore.current = nextSel;
    selRef.current = nextSel;
    setSel(nextSel);
    setPending(nextPending);
    onChange(stored(normal));
  };

  // Keep the caret where the model says after every render the editor caused.
  useLayoutEffect(() => {
    const element = root.current;
    const wanted = restore.current;
    if (!element || !wanted || document.activeElement !== element) return;
    restore.current = null;
    const a = posToDom(element, clampPos(docRef.current, wanted.anchor));
    const f = posToDom(element, clampPos(docRef.current, wanted.focus));
    if (a && f) window.getSelection()?.setBaseAndExtent(a[0], a[1], f[0], f[1]);
  });

  // The model's selection, brought up to date with the DOM. `selectionchange` arrives
  // asynchronously, so a command (Ctrl+B, a toolbar button, typed text) that runs
  // right after the selection moved must read the live selection, not the cache.
  const syncSelection = () => {
    const element = root.current;
    const selection = window.getSelection();
    if (!element || !selection || !selection.anchorNode || !element.contains(selection.anchorNode))
      return selRef.current;
    const anchor = domToPos(element, selection.anchorNode, selection.anchorOffset);
    const focus = selection.focusNode
      ? domToPos(element, selection.focusNode, selection.focusOffset)
      : anchor;
    if (!anchor || !focus) return selRef.current;
    const previous = selRef.current;
    if (
      previous.anchor.block === anchor.block &&
      previous.anchor.offset === anchor.offset &&
      previous.focus.block === focus.block &&
      previous.focus.offset === focus.offset
    )
      return previous;
    const next = { anchor, focus };
    selRef.current = next;
    setSel(next);
    setPending(null);
    return next;
  };

  useEffect(() => {
    const onSelection = () => void syncSelection();
    document.addEventListener('selectionchange', onSelection);
    return () => document.removeEventListener('selectionchange', onSelection);
  }, []);

  useEffect(() => {
    const element = root.current;
    if (!element) return;
    const onBeforeInput = (event: InputEvent) => {
      if (composing.current) return;
      event.preventDefault();
      if (disabled) return;
      const current = docRef.current;
      const cached = selRef.current;
      const range = syncSelection();
      // A pending style belongs to the caret it was chosen at.
      const pendingHere = range === cached ? pending : null;
      const [start] = ordered(range);
      switch (event.inputType) {
        case 'insertText':
        case 'insertReplacementText': {
          const text = event.data ?? event.dataTransfer?.getData('text/plain') ?? '';
          const style = pendingHere ?? undefined;
          const [next, caret] = insertText(current, range, text, style);
          commit(next, caret, null);
          return;
        }
        case 'insertParagraph': {
          const [next, caret] = splitBlock(current, range);
          commit(next, caret);
          return;
        }
        case 'insertLineBreak': {
          const [next, caret] = insertLineBreak(current, range);
          commit(next, caret);
          return;
        }
        case 'deleteContentBackward': {
          const [next, caret] = deleteBackward(current, range);
          commit(next, caret);
          return;
        }
        case 'deleteContentForward': {
          const [next, caret] = deleteForward(current, range);
          commit(next, caret);
          return;
        }
        case 'deleteWordBackward':
        case 'deleteWordForward': {
          if (!collapsed(range)) {
            const [next, caret] = deleteRange(current, range);
            commit(next, caret);
            return;
          }
          const text = blockText(current.blocks[start.block]);
          const backward = event.inputType === 'deleteWordBackward';
          if ((backward && start.offset === 0) || (!backward && start.offset === text.length)) {
            const [next, caret] = backward
              ? deleteBackward(current, range)
              : deleteForward(current, range);
            commit(next, caret);
            return;
          }
          const edge = wordBoundary(text, start.offset, backward ? -1 : 1);
          const [next, caret] = deleteRange(current, {
            anchor: start,
            focus: { block: start.block, offset: edge },
          });
          commit(next, caret);
          return;
        }
        case 'deleteSoftLineBackward':
        case 'deleteHardLineBackward': {
          const [next, caret] = deleteRange(current, {
            anchor: { block: start.block, offset: 0 },
            focus: range.focus,
          });
          commit(next, caret);
          return;
        }
        case 'deleteSoftLineForward':
        case 'deleteHardLineForward': {
          const end = blockText(current.blocks[start.block]).length;
          const [next, caret] = deleteRange(current, {
            anchor: range.anchor,
            focus: { block: start.block, offset: end },
          });
          commit(next, caret);
          return;
        }
        case 'deleteByCut':
        case 'deleteByDrag': {
          const [next, caret] = deleteRange(current, range);
          commit(next, caret);
          return;
        }
        case 'formatBold':
        case 'formatItalic':
        case 'formatUnderline':
          mark(
            event.inputType === 'formatBold'
              ? 'bold'
              : event.inputType === 'formatItalic'
                ? 'italic'
                : 'underline',
          );
          return;
        default:
          // Paste and drop arrive as their own events; history belongs to the cover's undo.
          return;
      }
    };
    element.addEventListener('beforeinput', onBeforeInput);
    return () => element.removeEventListener('beforeinput', onBeforeInput);
  });

  const inherited = (key: 'bold' | 'italic') => (key === 'bold' ? base.bold : base.italic);
  const familyAt = () => sharedStyle(doc, selRef.current, 'font') ?? base.family;
  const markOn = (key: Mark) =>
    collapsed(sel) && pending && pending[key] !== undefined
      ? Boolean(pending[key])
      : hasMark(doc, sel, key, key === 'underline' ? false : inherited(key));
  const canStyle = (key: 'bold' | 'italic') => {
    const family = familyAt();
    const bold = key === 'bold' ? !markOn('bold') : markOn('bold');
    const italic = key === 'italic' ? !markOn('italic') : markOn('italic');
    return variantAvailable(family, bold, italic);
  };
  const reason = (key: 'bold' | 'italic') => {
    const family = familyAt();
    const name = FAMILY_LABELS[family] ?? 'This imported font';
    return `${name} has no ${markOn(key === 'bold' ? 'italic' : 'bold') ? 'bold italic' : key} face. Choose another font for this text; PuzzlePress never fakes a face.`;
  };

  function mark(key: Mark) {
    const cached = selRef.current;
    const range = syncSelection();
    const pendingHere = range === cached ? pending : null;
    if (key !== 'underline' && !canStyle(key)) {
      setNotice(reason(key));
      return;
    }
    if (collapsed(range)) {
      const current = { ...styleAt(docRef.current, range.focus), ...(pendingHere ?? {}) };
      const on = current[key] ?? (key === 'underline' ? false : inherited(key));
      setPending({ ...current, [key]: !on });
      setNotice(`${key[0].toUpperCase()}${key.slice(1)} ${on ? 'off' : 'on'} for new text.`);
      root.current?.focus();
      return;
    }
    commit(
      toggleMark(docRef.current, range, key, key === 'underline' ? false : inherited(key)),
      range,
    );
  }
  const style = (patch: RunStyle) => {
    const cached = selRef.current;
    const range = syncSelection();
    const pendingHere = range === cached ? pending : null;
    if (collapsed(range)) {
      setPending({ ...styleAt(docRef.current, range.focus), ...(pendingHere ?? {}), ...patch });
      return;
    }
    commit(styleRange(docRef.current, range, patch), range);
  };
  const blockStyle = (patch: Omit<RichBlock, 'runs'>) =>
    commit(setBlocks(docRef.current, selRef.current, patch), selRef.current);
  const [first] = ordered(sel);
  const block = doc.blocks[first.block] ?? { runs: [] };
  const size = sharedStyle(doc, sel, 'size');
  const color = sharedStyle(doc, sel, 'color');
  const font = sharedStyle(doc, sel, 'font');

  const keys = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (!(event.ctrlKey || event.metaKey) || event.altKey) return;
    const key = event.key.toLowerCase();
    const map: Record<string, Mark> = { b: 'bold', i: 'italic', u: 'underline' };
    if (map[key]) {
      mark(map[key]);
      event.preventDefault();
    }
  };
  let number = 0;
  const hintId = hint ? `${id}-hint` : undefined;
  const toolbarId = `${id}-toolbar`;
  return (
    <div className={`rich-editor${disabled ? ' disabled' : ''}`}>
      <span className="rich-label" id={`${id}-label`}>
        {label}
      </span>
      <div
        className="rich-toolbar"
        role="toolbar"
        aria-label={`${label} formatting`}
        aria-controls={id}
        id={toolbarId}
        onMouseDown={(event) => {
          // Keep the text selection while clicking formatting buttons.
          if ((event.target as HTMLElement).closest('button')) event.preventDefault();
        }}
      >
        {(
          [
            ['bold', 'B', 'Bold', 'B'],
            ['italic', 'I', 'Italic', 'I'],
            ['underline', 'U', 'Underline', 'U'],
          ] as const
        ).map(([key, glyph, name, shortcut]) => {
          const unavailable = key !== 'underline' && !canStyle(key);
          return (
            <button
              key={key}
              type="button"
              className={`rich-mark rich-${key}`}
              aria-label={name}
              aria-pressed={markOn(key)}
              aria-keyshortcuts={`${MOD}+${shortcut}`}
              aria-disabled={unavailable || disabled ? true : undefined}
              title={
                unavailable ? reason(key) : `${name} (${MOD === 'Meta' ? '⌘' : 'Ctrl+'}${shortcut})`
              }
              onClick={() => !disabled && mark(key)}
            >
              {glyph}
            </button>
          );
        })}
        <select
          aria-label="Font for the selection"
          value={font ?? ''}
          disabled={disabled}
          onChange={(event) => style({ font: event.target.value || undefined })}
        >
          <option value="">Box font</option>
          {Object.entries(FAMILY_LABELS).map(([key, name]) => (
            <option key={key} value={key}>
              {name}
            </option>
          ))}
          {fonts.map(([key, name]) => (
            <option key={key} value={key}>
              {name}
            </option>
          ))}
        </select>
        <label className="rich-size">
          <span className="sr-only">Size of the selection in points</span>
          <input
            type="number"
            min={4}
            max={160}
            step={0.5}
            placeholder="Size"
            value={size ?? ''}
            disabled={disabled}
            onChange={(event) => {
              const next = event.target.value === '' ? undefined : Number(event.target.value);
              if (next === undefined || (next >= 4 && next <= 160)) style({ size: next });
            }}
          />
          <span aria-hidden="true">pt</span>
        </label>
        <label className="rich-color">
          <span className="sr-only">Color of the selection</span>
          <input
            type="color"
            value={color ?? '#252d28'}
            disabled={disabled}
            onChange={(event) => style({ color: event.target.value.toLowerCase() })}
          />
        </label>
        <span className="rich-divider" aria-hidden="true" />
        {(
          [
            ['left', 'Align left'],
            ['center', 'Align center'],
            ['right', 'Align right'],
          ] as const
        ).map(([align, name]) => (
          <button
            key={align}
            type="button"
            className={`rich-align rich-align-${align}`}
            aria-label={name}
            aria-pressed={block.align === align}
            disabled={disabled}
            onClick={() => blockStyle({ align: block.align === align ? undefined : align })}
          >
            <AlignIcon align={align} />
          </button>
        ))}
        <button
          type="button"
          aria-label="Bulleted list"
          aria-pressed={block.list === 'bullet'}
          disabled={disabled}
          onClick={() => blockStyle({ list: block.list === 'bullet' ? undefined : 'bullet' })}
        >
          •≡
        </button>
        <button
          type="button"
          aria-label="Numbered list"
          aria-pressed={block.list === 'number'}
          disabled={disabled}
          onClick={() => blockStyle({ list: block.list === 'number' ? undefined : 'number' })}
        >
          1.
        </button>
        <button
          type="button"
          aria-label="Heading"
          aria-pressed={block.type === 'heading'}
          disabled={disabled}
          onClick={() =>
            blockStyle({ type: block.type === 'heading' ? undefined : 'heading', list: undefined })
          }
        >
          H
        </button>
        <button
          type="button"
          aria-label="Clear formatting"
          title="Clear formatting from the selected paragraphs"
          disabled={disabled}
          onClick={() => commit(clearFormatting(docRef.current, selRef.current), selRef.current)}
        >
          Clear
        </button>
      </div>
      <div
        key={renderKey}
        ref={root}
        id={id}
        className={`rich-text-area${invalid ? ' invalid' : ''}`}
        role="textbox"
        aria-multiline="true"
        aria-labelledby={`${id}-label`}
        aria-describedby={[hintId, `${id}-notice`].filter(Boolean).join(' ')}
        aria-invalid={invalid ? true : undefined}
        aria-disabled={disabled ? true : undefined}
        contentEditable={!disabled}
        suppressContentEditableWarning
        spellCheck
        tabIndex={0}
        onKeyDown={keys}
        onPaste={(event) => {
          event.preventDefault();
          if (disabled) return;
          const text = event.clipboardData.getData('text/plain');
          const [next, caret] = insertText(docRef.current, selRef.current, text);
          commit(next, caret);
        }}
        onCopy={(event) => copy(event, false)}
        onCut={(event) => copy(event, true)}
        onDrop={(event) => event.preventDefault()}
        onCompositionStart={() => {
          composing.current = selRef.current;
        }}
        onCompositionEnd={(event) => {
          const start = composing.current;
          composing.current = null;
          if (!start) return;
          const [next, caret] = insertText(docRef.current, start, event.data);
          setRenderKey((n) => n + 1); // Discard the browser's composition DOM.
          commit(next, caret);
          requestAnimationFrame(() => root.current?.focus());
        }}
        style={{ fontFamily: SCREEN_FAMILY[base.family] }}
      >
        {doc.blocks.map((item, index) => {
          number = item.list === 'number' ? number + 1 : 0;
          const classes = ['rich-block'];
          if (item.type === 'heading') classes.push('rich-heading');
          if (item.list) classes.push(`rich-list rich-${item.list}`);
          return (
            <div
              key={index}
              data-block={index}
              data-number={item.list === 'number' ? `${number}.` : undefined}
              className={classes.join(' ')}
              style={{
                textAlign: item.align,
                marginTop: item.space_before ? `${Math.min(item.space_before, 24)}px` : undefined,
                marginBottom: item.space_after ? `${Math.min(item.space_after, 24)}px` : undefined,
                lineHeight: item.line_spacing,
              }}
            >
              {item.runs.length === 0 ? (
                <br />
              ) : (
                item.runs.map((run, r) => (
                  <span key={r} style={runCss(run, base)}>
                    {run.text}
                  </span>
                ))
              )}
            </div>
          );
        })}
      </div>
      <div className="rich-paragraph" role="group" aria-label="Paragraph spacing">
        <label>
          Line spacing
          <input
            type="number"
            min={0.8}
            max={3}
            step={0.05}
            placeholder="Box"
            value={block.line_spacing ?? ''}
            disabled={disabled}
            onChange={(event) => {
              const next = event.target.value === '' ? undefined : Number(event.target.value);
              if (next === undefined || (next >= 0.8 && next <= 3))
                blockStyle({ line_spacing: next });
            }}
          />
        </label>
        {(['space_before', 'space_after'] as const).map((key) => (
          <label key={key}>
            {key === 'space_before' ? 'Space before' : 'Space after'}
            <input
              type="number"
              min={0}
              max={72}
              step={1}
              placeholder="0"
              value={block[key] ?? ''}
              disabled={disabled}
              onChange={(event) => {
                const next = event.target.value === '' ? undefined : Number(event.target.value);
                if (next === undefined || (next >= 0 && next <= 72))
                  blockStyle({ [key]: next || undefined });
              }}
            />
            <span aria-hidden="true">pt</span>
          </label>
        ))}
      </div>
      {hint && (
        <p className="small muted field-hint" id={hintId}>
          {hint}
        </p>
      )}
      <p className="small rich-notice" id={`${id}-notice`} role="status" aria-live="polite">
        {notice}
      </p>
    </div>
  );

  function copy(event: React.ClipboardEvent<HTMLDivElement>, cut: boolean) {
    const range = selRef.current;
    if (collapsed(range)) return;
    event.preventDefault();
    const [start, end] = ordered(range);
    const text = docRef.current.blocks
      .slice(start.block, end.block + 1)
      .map((item, i, all) => {
        const value = blockText(item);
        const from = i === 0 ? start.offset : 0;
        const to = i === all.length - 1 ? end.offset : value.length;
        return value.slice(from, to);
      })
      .join('\n');
    event.clipboardData.setData('text/plain', text);
    if (cut && !disabled) {
      const [next, caret] = deleteRange(docRef.current, range);
      commit(next, caret);
    }
  }
}

function AlignIcon({ align }: { align: 'left' | 'center' | 'right' }) {
  const lines = [16, 10, 14];
  return (
    <svg viewBox="0 0 18 14" width="16" height="12" aria-hidden="true">
      {lines.map((width, i) => {
        const x = align === 'left' ? 1 : align === 'right' ? 17 - width : (18 - width) / 2;
        return <rect key={i} x={x} y={1 + i * 5} width={width} height={1.6} fill="currentColor" />;
      })}
    </svg>
  );
}
