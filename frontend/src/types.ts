// Short names for the API types. The shapes themselves live in
// api-types.ts, generated from the backend's OpenAPI schema (`npm run
// gen:api`) - so when a pydantic model changes, `tsc` fails here instead
// of the UI breaking at runtime. Only add aliases in this file, never
// hand-written shapes.
import type { components } from "./api-types";

type Schemas = components["schemas"];

export type ModelPart = Schemas["ModelPart"];
export type ModelInfo = Schemas["ModelInfo"];
export type FlagDef = Schemas["FlagDef"];
export type FlagType = FlagDef["type"];
export type StatusResponse = Schemas["StatusResponse"];
export type ServerState = StatusResponse["state"];
export type HealthResponse = Schemas["HealthResponse"];
export type RestartResponse = Schemas["RestartResponse"];
export type Preset = Schemas["Preset"];
export type StartRequest = Schemas["StartRequest"];
export type DeletedResponse = Schemas["DeletedResponse"];
export type BinaryInfo = Schemas["BinaryInfo"];

export type FlagValues = StartRequest["flags"];
