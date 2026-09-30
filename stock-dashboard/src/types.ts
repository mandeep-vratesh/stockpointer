import raw from './config/dashboard.config.json';

export type Op = 'lt' | 'lte' | 'gt' | 'gte' | 'eq' | 'neq' | 'between' | 'in' | 'ltField' | 'gtField';
export type Condition = {
  id: string; label: string; op: Op;
  value?: number | string; min?: number; max?: number; values?: (number | string)[]; field?: string;
};
export type ColumnCfg = {
  id: string; field: string; label: string; description: string; type: 'number' | 'text';
  format?: { decimals?: number; prefix?: string; suffix?: string };
  defaultWeight: number; defaultCondition: string; conditions: Condition[];
};
export type GroupCfg = { id: string; label: string; description: string; defaultWeight: number; columns: ColumnCfg[] };
export type DashboardConfig = {
  dataPath: string; folderRegex: string; fileName: string; symbolField: string; groupMembershipField: string;
  symbolGroups: { id: string; label: string }[]; defaultSymbolGroup: string;
  fixedColumns: { symbol: { label: string; description: string }; totalPoints: { label: string; description: string } };
  groups: GroupCfg[];
};
export const config = raw as unknown as DashboardConfig;

export const NONE = '-none-';
export type Filter = { min?: number; max?: number; contains?: string };
export type SavedSettings = {
  groupWeights: Record<string, number>; columnWeights: Record<string, number>;
  columnConditions: Record<string, string>; columnFilters: Record<string, Filter>;
  collapsedGroups: Record<string, boolean>; updatedAt?: number;
};
export type Settings = Required<Omit<SavedSettings, 'updatedAt'>>;
export type Handlers = {
  setGroupWeight: (id: string, n: number) => void;
  setColumnWeight: (id: string, n: number) => void;
  setCondition: (id: string, c: string) => void;
  setFilter: (id: string, f: Filter) => void;
  toggleGroup: (id: string) => void;
};
export type Meta = { settings: Settings; h: Handlers };
export type DataRow = Record<string, unknown>;
export type Row = { symbol: string; groups: string[]; data: DataRow };
export type Scored = { row: Row; colPts: Record<string, number>; groupPoints: Record<string, number>; total: number };
