import type { RichDoc } from './rich-text-model';
// Transport views only. Python owns all validation, generation and quality rules.
export interface Issue {
  path: string;
  code: string;
  message: string;
}
export interface Definition {
  id: string;
  title: string;
  theme: string;
  bank: string;
  target_ids: string[];
  difficulty: string;
}
export interface Profile {
  id: string;
  width: number;
  height: number;
  directions: string[];
  max_restarts: number;
  max_attempts: number;
}
export interface QualityConfig {
  max_word_reuse: number;
  target_similarity_threshold: number;
  grid_similarity_threshold: number;
  prohibited_words: string[];
}
export interface MatterItem {
  kind: string;
  title?: string;
  text?: string;
}
export interface Composition {
  front_matter: MatterItem[];
  puzzles: {
    start: string;
    layout?: 'single' | 'spread';
    dividers?: { start: 'any' | 'recto'; themes: ThemeDivider[] };
  };
  solutions: { placement: string; title?: string; per_page?: number; start?: string };
  back_matter: MatterItem[];
  page_numbers: {
    scheme: string;
    show_front_matter: boolean;
    show_solutions: boolean;
    show_back_matter: boolean;
  };
}
export interface Project {
  key: string;
  revision?: string;
  identity?: string;
  engine_version?: string;
  /** Derived by Python from the content section; never authored. */
  engine?: { kind: string; label: string };
  validation: { valid: boolean; issues: Issue[] };
  source?: {
    schema_version: number;
    book: {
      id: string;
      title: string;
      language: string;
      subtitle: string | null;
      description: string | null;
      author: string | null;
      imprint: string | null;
    };
    build: { seed: string };
    content: { items: string[] };
    output: { directory: string };
    word_search?: {
      banks: { id: string; entries: { id: string; display: string }[] }[];
      profiles: Profile[];
      puzzles: Definition[];
      quality: QualityConfig;
    };
    composition?: Composition;
    cover?: CoverConfig;
    publishing?: PublishingConfig;
    interior?: InteriorStyle;
    coloring?: ColoringSource;
    /** How the author files the book in the Library; read by nothing else. */
    catalog?: { subject?: string; collection?: string };
    /** The print profile (trim and paper) the author chose; builds use it. */
    print?: { profile: string };
  };
}
/** Python's lossless placement of one drawing inside its art box. */
export interface Placement {
  scale: number;
  x: number;
  y: number;
  /** contain (default, written only as absent) or fill (full-bleed profiles only). */
  fit?: 'contain' | 'fill';
}
/** What trimming does to a drawing that fills a full-bleed page (Python's measure). */
export interface BleedCrop {
  ink_pixels: number;
  hidden: number;
  trimmed: number;
  unsafe: number;
  visible_area: number;
}
/** What a new book can be created as (GET /api/project-types). */
export interface ProjectTypes {
  types: {
    kind: string;
    label: string;
    default_template: string;
    templates: { id: string; label: string; description: string }[];
  }[];
  profiles: {
    id: string;
    description: string;
    paper: string;
    trim: { width: number; height: number };
    /** Full bleed: coloring books only (Python refuses it for word search). */
    bleed?: boolean;
  }[];
}
/** The authored coloring section, as Python normalized it. */
export interface ColoringSource {
  version: number;
  artwork: { id: string; path: string; sha256: string; title: string | null }[];
  /** Publication order: a drawing, or a section divider. */
  pages: (
    { artwork: string; placement?: Placement } | { divider: { title: string; text?: string } }
  )[];
  layout: { blank_reverse: boolean; border: string };
}
/** Line-art preparation settings, as Python normalizes them (invert only when set). */
export interface Adjustments {
  grayscale: boolean;
  threshold: number | null;
  brightness: number;
  contrast: number;
  background_cleanup: number;
  despeckle: number;
  line_weight: number;
  invert?: boolean;
}
export interface Preparation {
  artwork: string;
  key: string;
  preparation_version: number;
  adjustments: Adjustments;
  saved_adjustments: Adjustments;
  measures: Record<string, number | number[] | string[] | null>;
  findings: ArtworkFinding[];
  blocking: boolean;
  images: { original: string; prepared: string; difference: string };
}
export interface ArtworkFinding {
  code: string;
  severity: 'blocking' | 'warning';
  message: string;
  actual: string | null;
  required: string | null;
}
export interface ArtworkEntry {
  id: string;
  title: string | null;
  path: string;
  sha256: string;
  pages: number[];
  adjustments: Adjustments;
  adjustments_applied: boolean;
  inspection: {
    info: {
      format: string;
      bytes: number;
      mode: string;
      pixels: [number, number];
      effective_dpi: number;
      transparent_pixels: boolean;
    };
    findings: ArtworkFinding[];
    blocking: boolean;
  } | null;
  error: { code: string; message: string } | null;
}
export interface ColoringListing {
  revision: string;
  report: {
    book_id: string;
    artwork: ArtworkEntry[];
    pages: number;
    unreferenced_files: string[];
    blocking: number;
    duplicates: {
      confirmed: {
        same_file: { sha256: string; artwork: string[]; pages: number[] }[];
        repeated_pages: { artwork: string; pages: number[] }[];
      };
      possible: { similar: { artwork: [string, string]; pages: number[] }[] };
      not_compared: string[];
      complete: boolean;
    };
  };
}
export interface Cell {
  x: number;
  y: number;
}
export interface Finding {
  code: string;
  message: string;
  puzzle_ids: string[];
  words: string[];
  severity: string;
}
export interface Scan {
  occurrences: { word: string; coordinates: Cell[] }[];
  truncated: boolean;
}
export interface PuzzleResult {
  id: string;
  title: string;
  theme: string;
  difficulty: string;
  seed: string;
  errors: Issue[];
  failure_stats: { attempts: number; restarts: number } | null;
  quality: {
    accidental_targets: Scan;
    prohibited: Scan;
    prohibited_screening_enabled: boolean;
  } | null;
  puzzle: {
    grid: string[];
    config: Omit<Profile, 'id'>;
    targets: { id: string; display: string; search: string }[];
    placements: { target_id: string; search: string; start: Cell; end: Cell; direction: string }[];
    stats: { attempts: number; restarts: number };
  } | null;
}
export interface Generation {
  report: {
    identity: string;
    success: boolean;
    clean: boolean;
    pipeline_version: number;
    puzzles: PuzzleResult[];
    findings: Finding[];
    quality_config: QualityConfig;
    reuse: { word: string; puzzle_ids: string[] }[];
    similarities: {
      left_id: string;
      right_id: string;
      shared_words: string[];
      target_jaccard: number;
      target_overlap: number;
      grid_agreement: number | null;
      identical_targets: boolean;
    }[];
  };
  verification: Record<string, { valid: boolean; issues: Issue[] } | null>;
  solution_cells: Record<string, Record<string, Cell[]>>;
}
export interface PlanPuzzle {
  id: string;
  ordinal: number;
  title: string;
  theme: string;
  seed: string;
  digest: string | null;
}
export interface PlanPage {
  index: number;
  side: 'recto' | 'verso';
  section: 'front_matter' | 'puzzles' | 'solutions' | 'back_matter';
  kind: string;
  number: { value: number; style: string; label: string; displayed: boolean };
  heading: string | null;
  matter: {
    title: string | null;
    subtitle: string | null;
    author: string | null;
    imprint: string | null;
    text: string | null;
  } | null;
  puzzle: PlanPuzzle | null;
  solution_page: number | null;
  solutions: { puzzle: PlanPuzzle; puzzle_page: number }[];
  blank: { reason: string; before_section: string | null } | null;
}
export interface PlanResult {
  plan: {
    plan_version: number;
    identity: string;
    book_id: string;
    complete: boolean;
    pages: PlanPage[];
    statistics: {
      logical_pages: number;
      front_matter_pages: number;
      puzzle_pages: number;
      solution_pages: number;
      back_matter_pages: number;
      blank_pages: number;
      puzzles: number;
      solutions: number;
      first_puzzle_page: number | null;
      first_solution_page: number | null;
    };
    diagnostics: Issue[];
  };
  verification: { valid: boolean; issues: Issue[] };
  generation: { success: boolean; clean: boolean; quality_findings: number };
}
// Print preview and preflight. Verdicts, geometry and page meaning come from Python.
export interface PtBox {
  x: number;
  y: number;
  width: number;
  height: number;
}
export interface Measure {
  actual: number | string;
  required: number | string | null;
  unit: string | null;
  comparison: string | null;
}
/** `info` never blocks; the coloring ruleset uses it for manual-review prompts. */
export type PreflightSeverity = 'error' | 'warning' | 'info';
export interface PreflightFinding {
  rule: string;
  severity: PreflightSeverity;
  scope: 'structural' | 'kdp';
  category: string;
  message: string;
  physical_page: number | null;
  logical_page: number | null;
  page_kind: string | null;
  side: 'recto' | 'verso' | null;
  folio: string | null;
  subject: string | null;
  region: string | null;
  bounds: PtBox | null;
  measure: Measure | null;
}
export interface PreflightRule {
  code: string;
  scope: 'structural' | 'kdp';
  category: string;
  severity: PreflightSeverity;
  title: string;
  description: string;
  basis: string;
  source: string;
  help: string;
  outcome: 'passed' | 'failed' | 'not_applicable' | 'not_evaluated';
  findings: number;
  note: string | null;
  measure: Measure | null;
}
export interface PreviewPage {
  physical_page: number;
  logical_page: number | null;
  kind: string | null;
  side: 'recto' | 'verso' | null;
  folio: string | null;
  description?: string;
  findings: { error: number; warning: number; info: number };
}
export interface PageGeometry {
  physical_page: number;
  /** The rendered page: the trim plus bleed on a full-bleed interior, else the trim. */
  media?: PtBox;
  trim: PtBox;
  live: PtBox;
  kdp_safe: PtBox | null;
  elements: { role: string; box: PtBox }[];
}
export interface PreflightReport {
  report_version: number;
  ruleset: { id: string; version: number; kdp_rules_checked: string };
  book_id: string;
  source_identity: string;
  profile: {
    id: string;
    version: number;
    description: string;
    trim: { name: string; width_in: number; height_in: number };
    bleed: boolean;
  } | null;
  artifacts: {
    pdf: { sha256: string; bytes: number } | null;
    manifest: { sha256: string; bytes: number } | null;
    interior_identity: string | null;
    expected_interior_identity: string | null;
    matches_layout: boolean;
  };
  page_count: number | null;
  structural: { status: 'valid' | 'invalid' };
  kdp: { status: 'ready' | 'not_ready' };
  counts: { severity: Record<string, number>; outcome: Record<string, number> };
  findings: PreflightFinding[];
  rules: PreflightRule[];
  pages: PreviewPage[];
}
export interface BuildDiagnostic {
  code: string;
  message: string;
  page: number | null;
  physical_page: number | null;
  kind: string | null;
  subject: string | null;
  region: string | null;
  actual: string | null;
  required: string | null;
}
export interface InteriorStatus {
  key: string;
  revision: string;
  ruleset: number;
  profiles?: { id: string; description: string; paper: string }[];
  profile?: string;
  /** The book's own print profile (Settings), when it chose one. */
  authored_profile?: string;
  state: 'missing' | 'current' | 'stale' | 'invalid';
  report: PreflightReport | null;
  preview: {
    pdf_sha256: string;
    page_count: number;
    scales: Record<string, number>;
    pages: PreviewPage[];
    geometry: PageGeometry[] | null;
  } | null;
  build?: { success: boolean; stage?: string; diagnostics?: BuildDiagnostic[] };
}
// Cover Studio. Geometry, crop windows, resolution and verdicts come from Python.
export interface CoverConfig {
  version: number;
  // Versions 1 and 2 only; version 3 places photographs as elements.
  layout?: 'full_wrap' | 'front_photo';
  image?: { path: string; sha256: string };
  crop?: Crop;
  type: {
    style: 'editorial' | 'bold' | 'minimal';
    position: 'top' | 'middle' | 'bottom';
    align: 'center' | 'left';
    tone: 'light' | 'dark';
  };
  legibility: 'shade' | 'panel' | 'none';
  background?: string;
  spine_text: 'auto' | 'none';
  // Plain text, or a rich text document once formatting is used (versions 2 and 3).
  back_text?: string | RichDoc;
  // Version 2: per-layer overrides, extra layers and imported fonts.
  text?: Partial<Record<TextRole, TextLayer>>;
  extra?: ExtraLayer[];
  fonts?: CoverFont[];
  // Version 3: independent region backgrounds and the element stack, bottom to top.
  regions?: Record<PanelRegion, RegionStyle>;
  elements?: CoverElement[];
}
export interface Crop {
  x: number;
  y: number;
  zoom: number;
}
export type PanelRegion = 'back' | 'spine' | 'front';
export type ElementRegion = PanelRegion | 'wrap';
export interface RegionStyle {
  color: string;
  gradient?: { to: string; direction: 'vertical' | 'horizontal' };
}
export interface ElementBox {
  x: number;
  y: number;
  width: number;
  height: number;
}
interface ElementBase {
  id: string;
  region: ElementRegion;
  visible?: boolean;
  locked?: boolean;
  name?: string;
}
export interface PhotoElement extends ElementBase {
  type: 'photo';
  image: { path: string; sha256: string };
  crop: Crop;
  box?: ElementBox;
}
export interface ShapeElement extends ElementBase {
  type: 'rect' | 'ellipse';
  box?: ElementBox;
  fill: string | null;
  stroke: string | null;
  stroke_width?: number;
  opacity?: number;
  rotation?: number;
}
export interface LineElement extends ElementBase {
  type: 'line';
  from: { x: number; y: number };
  to: { x: number; y: number };
  color: string;
  width: number;
}
export interface TextBoxElement extends ElementBase {
  type: 'text';
  box: ElementBox;
  // Plain text, or `rich` once formatting is used; never both.
  text?: string;
  rich?: RichDoc;
  font?: string;
  size: number;
  color: string;
  align: 'left' | 'center' | 'right';
  line_spacing: number;
  letter_spacing?: number;
  case?: 'as_written' | 'upper';
}
export type CoverElement = PhotoElement | ShapeElement | LineElement | TextBoxElement;
export type TextRole = 'title' | 'subtitle' | 'author' | 'back_text' | 'imprint';
export interface TextLayer {
  visible?: boolean;
  text?: string;
  font?: string;
  size?: number;
  color?: string;
  align?: 'left' | 'center' | 'right';
  line_spacing?: number;
  letter_spacing?: number;
  case?: 'as_written' | 'upper';
  offset?: { x: number; y: number };
}
export interface ExtraLayer extends Omit<TextLayer, 'text'> {
  id: string;
  panel: 'front' | 'back';
  text: string;
}
export interface CoverFont {
  id: string;
  path: string;
  sha256: string;
  license?: string | null;
  source?: string | null;
}
export interface FontFacts {
  path: string;
  problem: string | null;
  message?: string | null;
  sha256?: string;
  bytes?: number;
  container?: string;
  postscript_name?: string;
  family?: string;
  style?: string;
  full_name?: string;
  weight?: number;
  italic?: boolean;
  glyphs?: number;
  embedding?: 'installable' | 'editable' | 'preview_print';
  missing?: string[];
  reused?: boolean;
}
export interface PhotoOption extends CoverAsset {
  dpi?: { effective: number; max: number; zoom: number; minimum: number; sufficient: boolean };
}
export interface CoverLibrary {
  photos: PhotoOption[];
  fonts: FontFacts[];
  bundled_fonts: { key: string; family: string; style: string; missing: string[] }[];
}
export interface CoverAsset {
  path: string;
  problem: string | null;
  sha256?: string;
  format?: string;
  bytes?: number;
  pixels?: [number, number];
  orientation?: number;
  color?: string;
  reused?: boolean;
}
export type CoverRegion =
  | 'media'
  | 'trim'
  | 'back'
  | 'spine'
  | 'front'
  | 'back_safe'
  | 'front_safe'
  | 'spine_safe'
  | 'back_design'
  | 'front_design'
  | 'barcode'
  | 'barcode_keep_clear';
export interface CoverGeometry {
  page_count: number;
  paper: string;
  bleed_in: number;
  spine_width_in: number;
  spine_width_pt: number;
  width_in: number;
  height_in: number;
  spine_text_allowed: boolean;
  regions: Record<CoverRegion, PtBox>;
}
export interface CoverResolution {
  source_pixels: [number, number];
  used_pixels: [number, number];
  printed_inches: [number, number];
  effective_dpi: number;
  max_dpi: number;
  minimum_dpi: number;
  status: 'ok' | 'image_low_effective_dpi' | 'image_too_small';
}
export interface CoverSpine {
  allowed_by_page_count: boolean;
  rendered: boolean;
  reason: 'authored' | 'page_count' | 'spine_too_narrow' | null;
  size: number | null;
}
export interface CoverLayoutView {
  geometry: CoverGeometry;
  texts: {
    role: string;
    layer: string; // title, subtitle, author, back_text, imprint, spine or extra:<id>.
    text: string;
    panel: string;
    size: number;
    face: string;
    rotated: boolean;
    box: PtBox;
  }[];
  panels: { role: string; box: PtBox }[];
  // The first photograph (versions 1 and 2 have exactly one); null without photos.
  photo: CoverPhotoView | null;
  photos?: CoverPhotoView[];
  elements?: {
    role: string;
    layer: string; // element:<id>
    kind: 'photo' | 'rect' | 'ellipse' | 'line' | 'text';
    box: PtBox;
    bounds: PtBox;
    rotation: number;
    baked?: boolean;
  }[];
  regions?: Record<ElementRegion, { origin: PtBox; area: PtBox }>;
  warnings?: BuildDiagnostic[];
  resolution: CoverResolution | null;
  spine_text: CoverSpine;
}
export interface CoverPhotoView {
  role: string;
  layer: string;
  region: PtBox;
  window: { left: number; top: number; right: number; bottom: number };
  center: [number, number];
  pixels: [number, number, number, number];
  resolution: CoverResolution;
}
export interface CoverConversion {
  success: boolean;
  stage?: string;
  diagnostics?: BuildDiagnostic[];
  cover?: CoverConfig;
  identical?: boolean;
  layout?: CoverLayoutView;
  preview?: { pdf_sha256: string; scales: Record<string, number> };
}
export interface CoverPreset {
  id: string;
  name: string;
  description: string;
  cover: CoverConfig;
}
export interface CoverCheck {
  code: string;
  severity: 'error' | 'warning' | 'info';
  message: string;
  layer?: string;
}
export interface CoverDraft {
  success: boolean;
  stage?: string;
  diagnostics?: BuildDiagnostic[];
  interior?: {
    page_count: number;
    profile_id: string;
    paper: string;
    ink: string;
    trim_in: [number, number];
    stale: string | null;
  };
  cover_identity?: string;
  layout?: CoverLayoutView;
  checks?: CoverCheck[];
  buildable?: boolean;
  display?: Record<'title' | 'subtitle' | 'author' | 'imprint', string | null>;
  library?: CoverLibrary;
  preview?: { pdf_sha256: string; scales: Record<string, number> };
}
export interface CoverReport {
  report_version: number;
  ruleset: { id: string; version: number; kdp_rules_checked: string };
  state: string;
  cover_identity: { recorded: string | null; expected: string | null };
  interior: { page_count: number; paper: string; profile_id: string } | null;
  artifacts: {
    pdf: { sha256: string; bytes: number } | null;
    manifest: { sha256: string; bytes: number } | null;
    matches_render: boolean;
  };
  structural: { status: 'valid' | 'invalid' };
  kdp: { status: 'ready' | 'not_ready' };
  findings: PreflightFinding[];
  rules: PreflightRule[];
}
export interface CoverStatus {
  key: string;
  revision: string;
  state: 'no_config' | 'missing' | 'current' | 'stale' | 'invalid';
  report: CoverReport | null;
  layout?: CoverLayoutView | null;
  preview: { pdf_sha256: string; scales: Record<string, number> } | null;
  build?: { success: boolean; stage?: string; diagnostics?: BuildDiagnostic[] };
}
// Publishing. Metadata rules, readiness verdicts and the package come from Python.
export type ContentOrigin = 'unknown' | 'human' | 'ai_assisted' | 'ai_generated' | 'none';
/** Coloring books: the author's declared basis for publishing a kind of content. */
export type RightsBasis =
  | 'undecided'
  | 'own_work'
  | 'commissioned'
  | 'licensed'
  | 'public_domain'
  | 'ai_tool_terms'
  | 'none';
export type ConfirmationName = 'rights' | 'ai_disclosure' | 'metadata' | 'isbn';
// Version 2 stores the review identity Python reported for the confirmed content, or
// null; version 1 stored booleans, which Python never treats as current confirmations.
export type StoredConfirmation = string | boolean | null;
export interface PublishingConfig {
  version: number;
  description: string | null;
  keywords: string[];
  categories: string[];
  contributors: { role: string; name: string }[];
  audience: {
    sexually_explicit: boolean | null;
    reading_age: { minimum: number | null; maximum: number | null };
  };
  low_content: boolean | null;
  isbn: { mode: 'undecided' | 'kdp_free' | 'own' | 'none'; value: string | null };
  edition: number | null;
  series: { title: string; number: number | null } | null;
  ai_disclosure: {
    text: ContentOrigin;
    images: ContentOrigin;
    translations: ContentOrigin;
    /** Coloring books only. */
    interior_artwork?: ContentOrigin;
    cover_artwork?: ContentOrigin;
  };
  attestations: Record<ConfirmationName, StoredConfirmation>;
  notes: string | null;
  /** Coloring books only: rights declarations, recorded as written. */
  content_rights?: {
    interior_artwork: RightsBasis;
    cover_artwork: RightsBasis;
    text: RightsBasis;
    notes: string | null;
  };
}
export interface Confirmation {
  name: ConfirmationName;
  statement: string;
  covers: string;
  required: boolean;
  state: 'confirmed' | 'stale' | 'unconfirmed' | 'legacy';
  current: string;
  confirmed: string | null;
  message: string;
}
export interface PublishingFinding {
  code: string;
  severity: 'error' | 'warning' | 'info';
  scope: string;
  basis: string;
  source: { title: string; url: string };
  message: string;
  field: string | null;
  artifact: string | null;
  actual: number | string | null;
  required: number | string | null;
  action: string | null;
  area: 'publishing' | 'edit' | 'book' | 'print' | 'cover';
  related: string | null;
}
export interface PublishingRule {
  code: string;
  scope: string;
  severity: 'error' | 'warning' | 'info';
  title: string;
  basis: string;
  source: { title: string; url: string };
  outcome: 'passed' | 'failed' | 'not_applicable' | 'not_evaluated';
  findings: number;
  note: string | null;
}
export interface ArtifactVerdict {
  state: string;
  structural: string;
  kdp: string;
}
export interface PublishingVerdicts {
  metadata: 'missing' | 'valid' | 'invalid';
  disclosure: 'complete' | 'incomplete';
  attestations: 'complete' | 'incomplete';
  interior?: ArtifactVerdict;
  cover?: ArtifactVerdict;
  artifacts?: string;
  package?: 'ready' | 'not_ready';
}
export interface MetadataReport {
  ruleset: { id: string; version: number; kdp_rules_checked: string };
  publishing_identity: string | null;
  verdicts: PublishingVerdicts;
  confirmations: Confirmation[];
  findings: PublishingFinding[];
  rules: PublishingRule[];
}
export interface PublishingDraftCheck {
  metadata: MetadataReport;
  // The section as version 2, every confirmation unconfirmed; only for version 1.
  upgrade: PublishingConfig | null;
}
export interface ReadinessReport extends MetadataReport {
  statement: string;
  identities: Record<string, unknown>;
  print: {
    format: string;
    profile: { id: string; version: number };
    trim_in: [number, number];
    ink: string;
    paper: string;
    interior_bleed: boolean;
    page_count: number;
    cover: { width_in: number; height_in: number; spine_width_in: number; bleed_in: number } | null;
  } | null;
}
export interface PublishingStatus {
  key: string;
  revision: string;
  readiness: ReadinessReport;
  metadata_record: Record<string, unknown>;
  checklist: string;
  package: {
    identity: string | null;
    export: {
      state: 'none' | 'current' | 'stale' | 'damaged';
      identity: string | null;
      problem: string | null;
    };
    location: string;
    archive: string;
    files: { name: string; purpose: string }[];
  };
  cover_preview: { pdf_sha256: string } | null;
  export?: {
    success: boolean;
    code?: string;
    message?: string;
    identity?: string;
    archive?: boolean;
    files?: { name: string; sha256: string; bytes: number; purpose: string }[];
  };
}

// Book planning (planning.yaml). Python validates, analyses and decides readiness;
// these are the document and report as Python serializes them.
export type Evidence =
  | 'unknown'
  | 'verified_source'
  | 'unverified_source'
  | 'author_observation'
  | 'hypothesis'
  | 'preference';
export type WordSource =
  'unknown' | 'human' | 'public_reference' | 'licensed' | 'ai_assisted' | 'ai_generated';
export interface PlanWord {
  word: string;
  source: WordSource | null;
  reference: string | null;
  note: string | null;
}
export interface PlanPool {
  theme: string;
  source: WordSource;
  reference: string | null;
  entries: PlanWord[];
}
export interface PlanTheme {
  id: string;
  label: string;
  parent: string | null;
  required: boolean;
  puzzles: number | null;
  notes: string | null;
}
export interface PlanLevel {
  id: string;
  label: string;
  profile: string | null;
  width: number | null;
  height: number | null;
  directions: string[];
  words: { min: number | null; max: number | null };
  notes: string | null;
}
export interface PlannedPuzzle {
  id: string;
  theme: string;
  level: string | null;
  title: string | null;
  words: string[];
  notes: string | null;
}
export interface PlanQuestion {
  id: string;
  question: string;
  blocking: boolean;
  resolution: string | null;
}
export interface PlanNote {
  id: string;
  question: string | null;
  observation: string;
  evidence: Evidence;
  confidence: 'low' | 'medium' | 'high' | null;
  source: { citation: string | null; url: string | null; type: string | null };
  observed: string | null;
  relevance: string | null;
  notes: string | null;
  decision: string | null;
}
export interface PlanComparable {
  id: string;
  title: string;
  contributor: string | null;
  url: string | null;
  citation: string | null;
  format: string | null;
  trim: string | null;
  pages: number | null;
  puzzles: number | null;
  price: { amount: string; currency: string } | null;
  audience: string | null;
  strengths: string[];
  weaknesses: string[];
  positioning: string | null;
  observed: string | null;
  evidence: Evidence;
}
export interface PlanningSource {
  planning_version: number;
  concept: {
    summary: string | null;
    subject: string | null;
    reader_experience: string | null;
    scope: string | null;
  };
  positioning: {
    primary_audience: string | null;
    secondary_audience: string | null;
    candidate_audiences: string[];
    familiarity: string;
    tone: string | null;
    use_case: string | null;
    main_benefit: string | null;
    differentiation: string | null;
    evidence: string[];
    claims: { text: string; evidence: string[] }[];
  };
  structure: {
    puzzle_type: string | null;
    target_puzzles: number | null;
    print_profile: string | null;
    solutions: string;
    solutions_per_page: number | null;
    front_matter_pages: number | null;
    back_matter_pages: number | null;
  };
  difficulty: { strategy: string; levels: PlanLevel[] };
  themes: PlanTheme[];
  vocabulary: PlanPool[];
  puzzles: PlannedPuzzle[];
  constraints: {
    min_letters: number | null;
    max_letters: number | null;
    max_word_reuse: number | null;
    prohibited_words: string[];
    notes: string[];
  };
  questions: PlanQuestion[];
  research: PlanNote[];
  comparables: PlanComparable[];
  approval: string | null;
}
export interface PlanFinding {
  code: string;
  gate: string;
  severity: 'error' | 'warning' | 'info';
  basis: string;
  message: string;
  path: string | null;
  actual: string | number | null;
  expected: string | number | null;
  action: string | null;
  subjects: string[];
}
export type PlanningState =
  | 'draft'
  | 'needs_research'
  | 'needs_content'
  | 'structurally_valid'
  | 'production_feasible'
  | 'ready_for_approval'
  | 'approved';
export interface PlanningReport {
  report_version: number;
  ruleset: { id: string; version: number };
  book: { id: string; title: string };
  planning_identity: string;
  state: PlanningState;
  statement: string;
  gates: { gate: string; label: string; passed: boolean; blocking: string[] }[];
  approval: {
    status: 'none' | 'current' | 'stale';
    approved_identity: string | null;
    counts: boolean;
  };
  summary: {
    target_puzzles: number | null;
    allocated_puzzles: number;
    specified_puzzles: number;
    themes: number;
    levels: number;
    candidate_words: number;
    findings: { error: number; warning: number; info: number };
  };
  allocation: {
    id: string;
    label: string;
    parent: string | null;
    depth: number;
    required: boolean;
    allocated: number | null;
    specified: number;
    share: number | null;
  }[];
  levels: {
    id: string;
    label: string;
    rank: number;
    origin: string;
    width: number | null;
    height: number | null;
    directions: string[];
    words: { min: number; max: number };
    puzzles: number;
    supported: boolean;
  }[];
  progression: {
    id: string;
    title: string | null;
    theme: string;
    level: string | null;
    rank: number | null;
    words: number;
  }[];
  vocabulary: {
    theme: string;
    label: string | null;
    entries: number;
    usable: number;
    invalid: number;
    duplicates: number;
    shared: number;
    assigned: number;
    needed: number | null;
    sources: Record<string, number>;
    words: {
      word: string;
      search: string | null;
      source: WordSource;
      valid: boolean;
      duplicate: boolean;
      shared: boolean;
    }[];
  }[];
  research: {
    notes: number;
    evidence: Record<Evidence, number>;
    questions: number;
    open_questions: number;
    blocking_questions: number;
    comparables: number;
    sourced_comparables: number;
  };
  feasibility: {
    code: string;
    label: string;
    status: 'verified' | 'estimate' | 'unknown' | 'unsupported';
    detail: string;
    actual: string | number | null;
    limit: string | number | null;
  }[];
  page_estimate: {
    minimum: number | null;
    maximum: number | null;
    parts: Record<string, number | null>;
  };
  findings: PlanFinding[];
  boundary: string;
}
export interface PlanningStatus {
  key: string;
  book: { id: string; title: string };
  revision: string | null;
  source: PlanningSource | null;
  report: PlanningReport | null;
  options: PlanningOptions;
}
export interface PlanningOptions {
  print_profiles: { id: string; description: string }[];
  puzzle_types: string[];
  directions: string[];
}

// Asset library. References and every removal decision come from Python.
export interface AssetUse {
  source: 'saved' | 'draft';
  path: string;
  label: string;
  area: string;
}
export interface LibraryAsset {
  kind: 'photo' | 'font';
  path: string;
  name: string;
  bytes: number;
  sha256: string | null;
  facts: Record<string, unknown>;
  problem: string | null;
  uses: AssetUse[];
  in_use: boolean;
}
export interface TrashEntry {
  kind: 'photo' | 'font';
  trashed: string;
  restores_to: string;
  bytes: number;
  sha256: string;
}
export interface AssetListing {
  revision: string;
  assets: LibraryAsset[];
  unmanaged: string[];
  trash: TrashEntry[];
}
// Interior style (the book's interior section). Python resolves presets and renders pages.
export type ThemeId =
  | 'classic'
  | 'racing_orange'
  | 'classic_garage'
  | 'editorial_minimal'
  | 'high_contrast'
  | 'ink_saver';
export type PageLayoutId = 'classic' | 'bold_header' | 'clean_minimal' | 'large_readability';
// Version 2 theme overrides; absent keys keep the theme's value.
export interface LookOverrides {
  banner?: 'none' | 'rule' | 'outline' | 'solid';
  corners?: 'square' | 'rounded';
  background?: 'none' | 'header_band' | 'frame';
  motif?: 'none' | 'stripes' | 'chevrons';
  motif_intensity?: 'subtle' | 'medium' | 'bold';
  density?: 'compact' | 'balanced' | 'spacious';
  folio_style?: 'plain' | 'rule' | 'outline';
}
export interface InteriorStyle extends LookOverrides {
  version: number;
  preset?: 'classic' | 'editorial' | 'modern' | 'high_contrast'; // Version 1 only.
  theme?: ThemeId; // Version 2.
  layout?: PageLayoutId;
  colors?: { accent?: string; secondary?: string };
  folio?: 'center' | 'outside';
  title_page?: {
    layout?: 'minimal' | 'editorial' | 'color_block' | 'framed' | 'photo_feature';
    tint?: number;
    title_size?: number;
    align?: 'center' | 'left';
    rule?: boolean;
    photo?: { image: { path: string; sha256: string }; crop: Crop };
  };
  puzzle_pages?: {
    header_align?: 'center' | 'left';
    title_size?: number;
    title_bold?: boolean;
    theme_label?: boolean;
    theme_size?: number;
    header_rule?: boolean;
    grid_frame?: number;
    word_size?: number;
    word_columns?: number;
    word_rule?: boolean;
    word_position?: 'below' | 'above';
    word_align?: 'center' | 'left';
    word_weight?: 'regular' | 'bold';
    letter_scale?: 'standard' | 'large';
    grid_width?: number;
    puzzle_number?: boolean;
    answer_reference?: string;
  };
  solution_pages?: {
    caption_size?: number;
    mark_width?: number;
    muted_ink?: number;
    page_label?: string;
  };
  dividers?: {
    layout?: 'centered' | 'framed' | 'band';
    tint?: number;
    photos?: { theme: string; image: { path: string; sha256: string }; crop: Crop }[];
  };
}
export interface ThemeDivider {
  theme: string;
  title?: string;
  text?: string;
  quote?: string;
  attribution?: string;
}
export type SampleRole =
  | 'title'
  | 'instructions'
  | 'divider'
  | 'puzzle'
  | 'spread_left'
  | 'spread_right'
  | 'answers'
  | 'answers_last';
// Python's fit of one solutions-per-page choice for this book's largest grids.
export interface AnswerChoice {
  per_page: number;
  columns: number;
  rows: number;
  letter_size: number;
  minimum: number;
  grid: [number, number] | null;
  fits: boolean;
  comfortable: boolean;
}
export interface AnswerSummary {
  per_page: number;
  pages: number;
  last_page_solutions: number;
  first_page: number | null;
  choices: AnswerChoice[];
}
// The resolved version 2 look Python laid the draft out with.
export interface ResolvedLook {
  theme: ThemeId;
  layout: PageLayoutId;
  accent: string;
  secondary: string;
  accent_gray: number;
  secondary_gray: number;
  banner: string;
  motif: string;
  background: string;
  [key: string]: unknown;
}
export interface InteriorDraft {
  success: boolean;
  stage?: string;
  diagnostics?: BuildDiagnostic[];
  pdf_sha256?: string;
  page_count?: number;
  pages?: {
    index: number;
    physical_page: number;
    kind: string;
    folio: string | null;
    roles: SampleRole[];
  }[];
  design?: { look?: ResolvedLook; [key: string]: unknown };
  warnings?: BuildDiagnostic[];
  answers?: AnswerSummary | null;
}
export interface DesignCatalogue {
  themes: {
    id: ThemeId;
    name: string;
    description: string;
    look: ResolvedLook;
    design: Record<string, unknown>;
  }[];
  layouts: {
    id: PageLayoutId;
    name: string;
    description: string;
    look: Record<string, unknown>;
    design: Record<string, unknown>;
  }[];
}
export interface DesignImport {
  success: boolean;
  name?: string;
  interior?: InteriorStyle;
  issues?: Issue[];
}
// Editorial review: author judgments bound to Python's review identities.
export type ReviewState = 'not_reviewed' | 'needs_changes' | 'reviewed' | 'stale';
export interface RecordedReview {
  puzzle: string;
  status: 'not_reviewed' | 'needs_changes' | 'reviewed';
  content?: string;
  note?: string;
  reviewer?: string;
  reviewed_on?: string;
}
export interface PuzzleReviewState {
  puzzle: string;
  title: string;
  theme: string;
  identity: string;
  state: ReviewState;
  recorded: RecordedReview | null;
}
export interface ReviewSummary {
  total: number;
  reviewed: number;
  needs_changes: number;
  not_reviewed: number;
  stale: number;
  complete: boolean;
  require_all: boolean;
}
export interface ReviewStatusResponse {
  source_revision: string;
  revision: string | null;
  report: { summary: ReviewSummary; puzzles: PuzzleReviewState[]; orphaned: RecordedReview[] };
}
// Proof records and the production overview.
export interface ProofArtifacts {
  interior: string;
  interior_pdf: string;
  cover: string | null;
  cover_pdf: string | null;
}
export interface ProofRecordView {
  id: string;
  kind: 'print_previewer' | 'physical_proof';
  status: 'ordered' | 'received' | 'reviewed';
  decision: 'undecided' | 'changes_needed' | 'approved';
  artifacts: ProofArtifacts;
  received_on?: string;
  reviewed_on?: string;
  issues?: string[];
  note?: string;
}
export interface ProofState {
  record: ProofRecordView;
  current: boolean;
}
export interface ProofsResponse {
  revision: string | null;
  artifacts: ProofArtifacts | null;
  proofs: ProofState[];
  print_previewer: ProofState | null;
  physical_proof: ProofState | null;
}
export type ItemStatus =
  | 'completed'
  | 'needs_attention'
  | 'blocking'
  | 'not_applicable'
  | 'awaiting_review'
  | 'external_pending';
export interface ProductionItem {
  code: string;
  title: string;
  status: ItemStatus;
  basis: 'internal' | 'kdp_modeled' | 'author_judgment' | 'external';
  blocks_export: boolean;
  what: string;
  why: string;
  action: string | null;
  area: string;
  detail: string;
}
export interface ArtifactAssessment {
  artifacts: { name: string; state: string; reasons: string[]; depends_on: string[] }[];
  steps: { action: string; artifact: string; why: string; conditional: boolean }[];
  manual: string[];
  outdated: boolean;
}
export interface RebuildStepResult {
  action: string;
  status: 'succeeded' | 'failed' | 'skipped' | 'unchanged';
  message: string;
  stage: string | null;
  diagnostics: BuildDiagnostic[];
}
export interface ProductionStatus {
  key: string;
  revision: string;
  statement: string;
  items: ProductionItem[];
  stages: { code: string; title: string; reached: boolean | null; detail: string }[];
  proofing: { code: string; title: string; area: string }[];
  assessment: ArtifactAssessment;
  reviews: ReviewSummary;
  proofs: ProofsResponse;
  rebuild?: {
    success: boolean;
    code?: string;
    message?: string;
    results: RebuildStepResult[];
  };
}
// Cover templates. Python validates, applies and renders them; the gallery only shows results.
export interface CoverTemplateInfo {
  id: string;
  name: string;
  description: string;
  category: string;
  photo: 'required' | 'optional' | 'none';
  slots: number;
  builtin: boolean;
  palette: string[];
  fonts: string[];
  imported_fonts: string[];
  provenance: string | null;
  identity: string;
}
export interface TemplateGallery {
  templates: CoverTemplateInfo[];
  problems: { file: string; code: string; message: string }[];
  template?: CoverTemplateInfo;
}
export interface TemplatePreview {
  success: boolean;
  template: CoverTemplateInfo;
  stage?: string;
  diagnostics?: BuildDiagnostic[];
  cover?: CoverConfig;
  missing_slots?: number[];
  replaced?: string[];
  kept?: string[];
  current?: {
    title: string;
    subtitle: string | null;
    author: string | null;
    imprint: string | null;
  };
  checks?: CoverCheck[];
  buildable?: boolean;
  preview?: { pdf_sha256: string; scales: Record<string, number> };
}
// Coloring plans: Python's verified page sequence of a coloring draft, with the page
// geometry (PDF points, origin bottom-left) the composer outlines.
export interface ColoringPlanPage {
  index: number;
  side: 'recto' | 'verso';
  section: 'front_matter' | 'artwork' | 'back_matter';
  kind: string;
  number: { value: number; style: string; label: string; displayed: boolean };
  matter: { title: string | null; text: string | null } | null;
  blank: { reason: string; before_section: string | null } | null;
  artwork?: { entry: number; id: string; ordinal: number; title: string | null; prepared: string };
  divider?: { title: string; text: string | null };
}
interface PtRect {
  x: number;
  y: number;
  width: number;
  height: number;
}
export interface ColoringPlanResult {
  plan: {
    complete: boolean;
    pages: ColoringPlanPage[];
    statistics: Record<string, number | null>;
    diagnostics: Issue[];
  };
  verification: { valid: boolean; issues: Issue[] };
  artwork: { failures: { id: string; code: string; message: string }[] };
  geometry: {
    profile: string;
    bleed?: boolean;
    trim: { width: number; height: number };
    /** The PDF page: the trim plus bleed on a full-bleed profile, else the trim. */
    media?: { width: number; height: number };
    border: string;
    sides: Record<
      'recto' | 'verso',
      {
        live: PtRect;
        art: PtRect;
        media?: PtRect;
        trim_box?: PtRect;
        fill?: PtRect | null;
        safe?: PtRect | null;
      }
    >;
  };
  /** By physical page: where Python places each drawing and its effective DPI. */
  placements?: Record<
    string,
    {
      entry: number;
      fit?: 'contain' | 'fill';
      /** The printed area: the drawing itself, or the fill area it is clipped to. */
      box?: PtRect;
      /** A filling drawing's whole extent, beyond what prints. */
      drawing?: PtRect;
      effective_dpi?: number;
      pixels: { width: number; height: number };
      placement: Placement;
      crop?: BleedCrop | null;
      /** fill_needs_bleed: the build refuses this page; nothing is drawn as printed. */
      error?: string;
    }
  >;
}

// Book audit (GET /api/projects/{key}/audit): Python's read-only recommendations.
export interface AuditRecommendation {
  code: string;
  priority: 'high' | 'medium' | 'low';
  category: 'listing' | 'print' | 'content' | 'series' | 'evidence';
  basis: 'kdp_help' | 'measured' | 'judgment';
  title: string;
  evidence: string;
  action: string;
  area: string;
  field: string | null;
  source: string | null;
  pages: number[];
  puzzles: string[];
}

export interface AuditLevel {
  profile: string;
  puzzles: number;
  first_puzzle: string;
  last_puzzle: string;
  grids: string[];
  words: { min: number; max: number };
  allowed_directions: number;
  allows_diagonal: boolean;
  allows_backward: boolean;
  placed_diagonal: { min: number; max: number };
  placed_backward: { min: number; max: number };
  longest_word: number;
}

export interface AuditReport {
  kind: 'puzzlepress-book-audit';
  audit_version: number;
  book_id: string;
  engine: string;
  title: string;
  page_count: number | null;
  counts: { high: number; medium: number; low: number };
  recommendations: AuditRecommendation[];
  manual_checks: { code: string; title: string; why: string; status: string }[];
  levels: AuditLevel[];
  compared_books: string[];
  not_assessed: string[];
  statement: string;
}

export interface AuditResponse {
  key: string;
  revision: string;
  audit: AuditReport;
  markdown: string;
  collection: string | null;
  compared: string[];
}
