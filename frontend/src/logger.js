/**
 * Structured logging configuration for frontend services.
 */
const winston = require('winston');
const path = require('path');

/**
 * Create a structured logger with JSON output and performance metrics.
 * @param {string} serviceName - Name of the service
 * @param {string} logLevel - Log level (debug, info, warn, error)
 * @returns {winston.Logger} Configured logger instance
 */
function createLogger(serviceName, logLevel = 'info') {
  const logger = winston.createLogger({
    level: logLevel,
    format: winston.format.combine(
      winston.format.timestamp({ format: 'YYYY-MM-DD HH:mm:ss.SSS' }),
      winston.format.errors({ stack: true }),
      winston.format.json()
    ),
    defaultMeta: { service: serviceName },
    transports: [
      new winston.transports.Console({
        format: winston.format.combine(
          winston.format.colorize(),
          winston.format.printf(({ timestamp, level, message, service, ...meta }) => {
            const metaStr = Object.keys(meta).length ? JSON.stringify(meta) : '';
            return `${timestamp} [${service}] ${level}: ${message} ${metaStr}`;
          })
        )
      })
    ]
  });

  return logger;
}

/**
 * Performance tracking context for measuring operation duration.
 */
class PerformanceContext {
  constructor(logger, operationName, metadata = {}) {
    this.logger = logger;
    this.operationName = operationName;
    this.metadata = metadata;
    this.startTime = Date.now();
    this.logger.info('operation_started', {
      operation: operationName,
      ...metadata
    });
  }

  /**
   * Mark operation as completed and log duration.
   * @param {object} additionalData - Additional data to log
   */
  complete(additionalData = {}) {
    const duration = Date.now() - this.startTime;
    this.logger.info('operation_completed', {
      operation: this.operationName,
      duration_ms: duration,
      ...this.metadata,
      ...additionalData
    });
  }

  /**
   * Mark operation as failed and log error.
   * @param {Error} error - The error that occurred
   * @param {object} additionalData - Additional data to log
   */
  error(error, additionalData = {}) {
    const duration = Date.now() - this.startTime;
    this.logger.error('operation_failed', {
      operation: this.operationName,
      duration_ms: duration,
      error: error.message,
      stack: error.stack,
      ...this.metadata,
      ...additionalData
    });
  }
}

module.exports = {
  createLogger,
  PerformanceContext
};
