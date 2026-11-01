import type { components } from "./schema";

export type Recording = components["schemas"]["Recording"];
export type InputLimits = components["schemas"]["InputLimits"];
export type RecordingSummary = components["schemas"]["RecordingSummary"];
export type RecordingDetail = components["schemas"]["RecordingDetail"];
export type Transcript = components["schemas"]["Transcript"];
export type Turn = components["schemas"]["Turn"];
export type Speaker = components["schemas"]["Speaker"];
export type Job = components["schemas"]["Job"];
export type Readiness = components["schemas"]["Readiness"];
export type ModelDownload = components["schemas"]["ModelDownload"];
export type SpeechModel = NonNullable<ModelDownload["model"]>;
export type Mode = Readiness["mode"];
export type CliConnection = components["schemas"]["CliConnection"];
export type CliProvider = CliConnection["provider"];
export type Analysis = components["schemas"]["AnalysisVersion"];
export type Fact = components["schemas"]["Fact"];
export type EditRequest = components["schemas"]["EditRequest"];

export type Sentence = components["schemas"]["Sentence"];
export type FormOption = components["schemas"]["FormOption"];
export type AnalysisForm = FormOption["id"];

export type AnalysisPreferences = components["schemas"]["AnalysisSettings"];
export type AnalysisOptions = components["schemas"]["AnalysisOptions"];
