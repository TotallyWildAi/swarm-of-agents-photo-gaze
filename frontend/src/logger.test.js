/**
 * Tests for structured logging functionality.
 */
const { createLogger, PerformanceContext } = require('./logger');

describe('Logger Configuration', () => {
  test('createLogger returns a valid logger instance', () => {
    const logger = createLogger('test-service');
    expect(logger).toBeDefined();
    expect(typeof logger.info).toBe('function');
    expect(typeof logger.error).toBe('function');
    expect(typeof logger.warn).toBe('function');
  });

  test('createLogger accepts custom log level', () => {
    const logger = createLogger('test-service', 'debug');
    expect(logger).toBeDefined();
  });
});

describe('PerformanceContext', () => {
  let logger;

  beforeEach(() => {
    logger = createLogger('test-service');
    logger.info = jest.fn();
    logger.error = jest.fn();
  });

  test('PerformanceContext logs operation start', () => {
    const ctx = new PerformanceContext(logger, 'test_op', { userId: '123' });
    expect(logger.info).toHaveBeenCalledWith('operation_started', {
      operation: 'test_op',
      userId: '123'
    });
  });

  test('PerformanceContext.complete logs operation completion', () => {
    const ctx = new PerformanceContext(logger, 'test_op');
    logger.info.mockClear();
    ctx.complete({ result: 'success' });
    expect(logger.info).toHaveBeenCalledWith('operation_completed', {
      operation: 'test_op',
      duration_ms: expect.any(Number),
      result: 'success'
    });
  });

  test('PerformanceContext.error logs operation failure', () => {
    const ctx = new PerformanceContext(logger, 'test_op');
    const testError = new Error('Test error');
    logger.error.mockClear();
    ctx.error(testError);
    expect(logger.error).toHaveBeenCalledWith('operation_failed', {
      operation: 'test_op',
      duration_ms: expect.any(Number),
      error: 'Test error',
      stack: expect.any(String)
    });
  });

  test('PerformanceContext measures duration correctly', (done) => {
    const ctx = new PerformanceContext(logger, 'timed_op');
    logger.info.mockClear();
    setTimeout(() => {
      ctx.complete();
      const call = logger.info.mock.calls[0];
      expect(call[1].duration_ms).toBeGreaterThanOrEqual(50);
      done();
    }, 50);
  });
});
