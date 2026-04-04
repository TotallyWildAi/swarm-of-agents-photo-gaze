/**
 * Tests for Express application with logging.
 */
const request = require('supertest');
const app = require('./index');

describe('Express Application', () => {
  test('GET /api/health returns 200 with healthy status', async () => {
    const response = await request(app).get('/api/health');
    expect(response.status).toBe(200);
    expect(response.body.status).toBe('healthy');
  });

  test('GET /api/data returns 200 with data', async () => {
    const response = await request(app).get('/api/data?user_id=123');
    expect(response.status).toBe(200);
    expect(response.body.items).toBeDefined();
    expect(Array.isArray(response.body.items)).toBe(true);
  });

  test('GET /api/nonexistent returns 404', async () => {
    const response = await request(app).get('/api/nonexistent');
    expect(response.status).toBe(404);
  });
});
