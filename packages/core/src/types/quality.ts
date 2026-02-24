import { z } from 'zod';

/**
 * Result status of a quality gate check
 */
export const GateStatusSchema = z.enum(['pass', 'fail', 'warn', 'skip'] as const);

export type GateStatus = z.infer<typeof GateStatusSchema>;

/**
 * Severity level of a quality gate failure
 */
export const SeveritySchema = z.enum(['critical', 'high', 'medium', 'low'] as const);

export type Severity = z.infer<typeof SeveritySchema>;

/**
 * Result from executing a single quality gate
 */
export const GateResultSchema = z.object({
  /** Gate identifier */
  gateId: z.string(),
  /** Human-readable gate name */
  name: z.string(),
  /** Pass/fail/warn/skip status */
  status: GateStatusSchema,
  /** Severity level if failed */
  severity: SeveritySchema,
  /** Metric value if applicable */
  metric: z.number().optional(),
  /** Threshold value for comparison */
  threshold: z.number().optional(),
  /** Detailed message explaining result */
  message: z.string().optional(),
});

export type GateResult = z.infer<typeof GateResultSchema>;

/**
 * A single violation found in code
 */
export const FixViolationSchema = z.object({
  /** Violation identifier */
  id: z.string(),
  /** Severity of violation */
  severity: SeveritySchema,
  /** File path containing violation */
  file: z.string(),
  /** Line number of violation, if applicable */
  line: z.number().int().positive().optional(),
  /** Metric data related to violation */
  metrics: z.record(z.unknown()).optional(),
  /** List of instructions to fix violation */
  instructions: z.array(z.string()),
});

export type FixViolation = z.infer<typeof FixViolationSchema>;

/**
 * Constraints for applying fixes
 */
export const FixConstraintsSchema = z.object({
  /** Whether new dependencies should not be added */
  noNewDeps: z.boolean().optional(),
  /** Files that must not be touched */
  doNotTouch: z.array(z.string()).optional(),
  /** Maximum number of retry iterations allowed */
  maxRetries: z.number().int().positive().optional(),
});

export type FixConstraints = z.infer<typeof FixConstraintsSchema>;

/**
 * Fix packet v2 with violations and constraints
 * Provides actionable guidance for remediation
 */
export const FixPacketV2Schema = z.object({
  /** List of violations to fix */
  violations: z.array(FixViolationSchema),
  /** Constraints for applying fixes */
  constraints: FixConstraintsSchema,
  /** Timestamp when packet was generated */
  generatedAt: z.string().datetime().optional(),
  /** Unique packet identifier */
  id: z.string().uuid().optional(),
});

export type FixPacketV2 = z.infer<typeof FixPacketV2Schema>;

/**
 * Result status of a test execution
 */
export const TestStatusSchema = z.enum(['passed', 'failed', 'skipped'] as const);

export type TestStatus = z.infer<typeof TestStatusSchema>;

/**
 * Result from running a single test
 */
export const TestResultSchema = z.object({
  /** Test name or identifier */
  name: z.string(),
  /** Test execution status */
  status: TestStatusSchema,
  /** Duration of test execution in milliseconds */
  durationMs: z.number().int().nonnegative(),
  /** Error message if test failed */
  error: z.string().optional(),
  /** Stack trace if test failed */
  stackTrace: z.string().optional(),
  /** Additional test metadata */
  metadata: z.record(z.unknown()).optional(),
});

export type TestResult = z.infer<typeof TestResultSchema>;

/**
 * Aggregated test suite results
 */
export const TestSuiteResultSchema = z.object({
  /** Suite identifier or name */
  suiteName: z.string(),
  /** Individual test results */
  tests: z.array(TestResultSchema),
  /** Total tests executed */
  totalTests: z.number().int().nonnegative(),
  /** Number of passing tests */
  passedTests: z.number().int().nonnegative(),
  /** Number of failing tests */
  failedTests: z.number().int().nonnegative(),
  /** Number of skipped tests */
  skippedTests: z.number().int().nonnegative(),
  /** Code coverage percentage */
  coverage: z.number().min(0).max(100).optional(),
  /** Total duration in milliseconds */
  durationMs: z.number().int().nonnegative(),
});

export type TestSuiteResult = z.infer<typeof TestSuiteResultSchema>;

/**
 * Quality gate execution report
 */
export const QualityReportSchema = z.object({
  /** Report identifier */
  id: z.string().uuid(),
  /** All gate results */
  gateResults: z.array(GateResultSchema),
  /** Overall pass/fail status */
  overallStatus: GateStatusSchema,
  /** Number of critical failures */
  criticalFailures: z.number().int().nonnegative(),
  /** Timestamp of report generation */
  generatedAt: z.string().datetime(),
  /** Duration of quality checks in milliseconds */
  durationMs: z.number().int().nonnegative(),
  /** Associated fix packet if failures found */
  fixPacket: FixPacketV2Schema.optional(),
});

export type QualityReport = z.infer<typeof QualityReportSchema>;
