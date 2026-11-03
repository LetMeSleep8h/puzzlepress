import { fireEvent, render, screen } from '@testing-library/react';
import { expect, test, vi } from 'vitest';
import { RichTextEditor } from './rich-text';

// `selectionchange` is delivered asynchronously. A shortcut pressed right after the
// selection moved (before that event) must still format the selected text.
test('Ctrl+B formats a selection made just before, without waiting for selectionchange', () => {
  const onChange = vi.fn();
  render(
    <RichTextEditor
      id="back"
      label="Back-cover text"
      value="Twenty word searches"
      onChange={onChange}
      baseFace="sans"
      fonts={[]}
      maxLength={1200}
    />,
  );
  const editor = screen.getByRole('textbox', { name: 'Back-cover text' });
  editor.focus();
  const walker = document.createTreeWalker(editor, NodeFilter.SHOW_TEXT);
  const text = walker.nextNode()!;
  expect(text.textContent).toContain('Twenty');
  // Select "Twenty" and press Ctrl+B in the same task, before selectionchange runs.
  window.getSelection()!.setBaseAndExtent(text, 0, text, 'Twenty'.length);
  fireEvent.keyDown(editor, { key: 'b', ctrlKey: true });
  expect(onChange).toHaveBeenCalledTimes(1);
  const saved = onChange.mock.calls[0][0] as { blocks: { runs: Record<string, unknown>[] }[] };
  expect(saved.blocks[0].runs[0]).toEqual({ text: 'Twenty', bold: true });
  expect(saved.blocks[0].runs[1]).toMatchObject({ text: ' word searches' });
});

test('typing replaces a selection made just before, without waiting for selectionchange', () => {
  const onChange = vi.fn();
  render(
    <RichTextEditor
      id="back"
      label="Back-cover text"
      value="Twenty word searches"
      onChange={onChange}
      baseFace="sans"
      fonts={[]}
      maxLength={1200}
    />,
  );
  const editor = screen.getByRole('textbox', { name: 'Back-cover text' });
  editor.focus();
  const text = document.createTreeWalker(editor, NodeFilter.SHOW_TEXT).nextNode()!;
  window.getSelection()!.setBaseAndExtent(text, 0, text, 'Twenty'.length);
  editor.dispatchEvent(
    new InputEvent('beforeinput', { inputType: 'insertText', data: 'Many', cancelable: true }),
  );
  expect(onChange).toHaveBeenCalledTimes(1);
  expect(onChange.mock.calls[0][0]).toBe('Many word searches');
});
