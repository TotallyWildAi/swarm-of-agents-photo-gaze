/**
 * Express application with structured logging.
 */
const express = require('express');
const { createLogger, PerformanceContext } = require('./logger');

const app = express();
const logger = createLogger('frontend-service', 'info');
const PORT = process.env.PORT || 3000;

// Middleware to log all requests
app.use((req, res, next) => {
  req.startTime = Date.now();
  logger.info('request_received', {
    method: req.method,
    path: req.path,
    ip: req.ip
  });

  res.on('finish', () => {
    const duration = Date.now() - req.startTime;
    logger.info('request_completed', {
      method: req.method,
      path: req.path,
      status: res.statusCode,
      duration_ms: duration
    });
  });

  next();
});

// Health check endpoint
app.get('/api/health', (req, res) => {
  const ctx = new PerformanceContext(logger, 'health_check');
  try {
    ctx.complete();
    res.json({ status: 'healthy' });
  } catch (error) {
    ctx.error(error);
    res.status(500).json({ error: 'Health check failed' });
  }
});

// Data endpoint
app.get('/api/data', (req, res) => {
  const ctx = new PerformanceContext(logger, 'get_data', {
    user_id: req.query.user_id
  });

  try {
    const backendData = { items: [1, 2, 3] };
    ctx.complete({ items_count: backendData.items.length });
    res.json(backendData);
  } catch (error) {
    ctx.error(error);
    res.status(500).json({ error: 'Failed to fetch data' });
  }
});

// Error handling middleware
app.use((err, req, res, next) => {
  logger.error('unhandled_exception', {
    error: err.message,
    stack: err.stack,
    path: req.path
  });
  res.status(500).json({ error: 'Internal server error' });
});

// Start server
if (require.main === module) {
  app.listen(PORT, () => {
    logger.info('server_started', {
      port: PORT,
      environment: process.env.NODE_ENV || 'development'
    });
  });
}

module.exports = app;
