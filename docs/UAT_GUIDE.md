# User Acceptance Testing (UAT) Guide

## Overview

This guide provides comprehensive instructions for conducting User Acceptance Testing (UAT) of the Photo Similarity Finder system. UAT validates that the system meets user expectations and business requirements through realistic end-to-end workflows.

## UAT Objectives

1. **Functional Validation**: Verify all features work as designed
2. **Performance Validation**: Confirm system meets performance requirements
3. **User Experience**: Validate UI/UX meets user expectations
4. **Data Integrity**: Ensure data consistency across components
5. **Error Handling**: Verify graceful error handling and recovery
6. **Integration**: Confirm all components work together seamlessly

## Test Environment Setup

### Prerequisites

- Python 3.9+
- Node.js 16+
- PostgreSQL 12+
- Qdrant (Docker or standalone)
- 2GB+ free disk space for sample photos

### Installation

```bash
# Backend setup
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Frontend setup
cd frontend
npm install
cd ..

# Database setup
alembic upgrade head
```

### Start Services

```bash
# Terminal 1: Backend
uvicorn app.main:app --reload --port 8000

# Terminal 2: Frontend
cd frontend && npm start

# Terminal 3: Qdrant (if using Docker)
docker run -p 6333:6333 qdrant/qdrant
```

## Sample Photo Collections

### Collection 1: Vacation Photos

**Purpose**: Test similarity detection with multiple similar scenes

**Contents**:
- 3-5 photos of the same beach/landscape from different angles
- 2-3 photos of the same sunset
- 2-3 group photos with similar composition

**Expected Results**:
- Similar photos grouped together with threshold 0.8+
- Different scenes separated into different groups

### Collection 2: Screenshots

**Purpose**: Test duplicate/near-duplicate detection

**Contents**:
- 2-3 identical or near-identical screenshots
- Screenshots with minor UI changes

**Expected Results**:
- Identical screenshots grouped with threshold 0.95+
- Near-duplicates grouped with threshold 0.85+

### Collection 3: Mixed Photos

**Purpose**: Test system with diverse photo types

**Contents**:
- Portraits (faces)
- Landscapes
- Architecture
- Close-ups
- Different formats (JPEG, PNG, WebP)
- Different dimensions (mobile, desktop, print)

**Expected Results**:
- Similar photo types grouped together
- Different types separated
- All formats processed correctly

## UAT Test Scenarios

### Scenario 1: Basic Folder Scanning

**Steps**:
1. Open Photo Similarity Finder UI
2. Click "Select Folder"
3. Navigate to sample photo collection
4. Click "Scan"

**Expected Results**:
- Progress bar appears and updates in real-time
- All photos are discovered and listed
- Scan completes in < 30 seconds for 100 photos
- No errors or warnings in console

### Scenario 2: Similarity Search

**Steps**:
1. After scanning completes, adjust similarity threshold slider
2. Set threshold to 0.8
3. Click "Find Similar Photos"

**Expected Results**:
- Similar photo groups appear
- Each group shows similarity score
- Thumbnails load quickly
- Groups are logically organized

### Scenario 3: Threshold Adjustment

**Steps**:
1. Adjust threshold slider from 0.7 to 0.95
2. Observe changes in grouping

**Expected Results**:
- Lower threshold (0.7): More groups, larger groups
- Higher threshold (0.95): Fewer groups, stricter matching
- Results update smoothly without lag

### Scenario 4: Pagination

**Steps**:
1. With large photo collection (100+), navigate through pages
2. Click "Next" and "Previous" buttons

**Expected Results**:
- Pages load quickly
- Correct photos displayed on each page
- Page indicators accurate

### Scenario 5: Error Handling

**Steps**:
1. Try to scan non-existent folder
2. Try to scan a file instead of folder
3. Try to scan folder with no images

**Expected Results**:
- Clear error messages displayed
- Suggestions for resolution provided
- UI remains responsive
- No crashes or unhandled exceptions

## Running Automated UAT Tests

### Run All UAT Tests

```bash
pytest tests/test_uat.py -v
```

### Run Specific Test Class

```bash
pytest tests/test_uat.py::TestUATFolderScanning -v
```

### Run with Coverage

```bash
pytest tests/test_uat.py -v --cov=app --cov-report=html
```

### Run with Performance Profiling

```bash
pytest tests/test_uat.py::TestUATPerformance -v -s
```

## Feedback Collection

See [UAT Feedback Template](UAT_FEEDBACK.md) for structured feedback collection.

### Key Metrics to Track

1. **Functionality**: % of features working as expected
2. **Performance**: Scan time, search time, UI responsiveness
3. **Usability**: Ease of use, clarity of UI, intuitiveness
4. **Reliability**: Crashes, errors, data loss
5. **Data Quality**: Accuracy of similarity detection

## Critical Issues Resolution

### Issue Severity Levels

**Critical** (Blocks UAT):
- System crashes or hangs
- Data loss or corruption
- Core feature completely non-functional
- Security vulnerabilities

**High** (Significant impact):
- Feature partially non-functional
- Performance significantly below requirements
- Incorrect results in similarity detection
- UI unusable in certain scenarios

**Medium** (Minor impact):
- UI/UX improvements needed
- Performance could be better
- Edge cases not handled

**Low** (Nice to have):
- Documentation improvements
- Minor UI tweaks
- Performance optimizations

### Issue Resolution Process

1. **Report**: Document issue with steps to reproduce
2. **Triage**: Assign severity level
3. **Fix**: Implement fix in development branch
4. **Test**: Verify fix with automated tests
5. **Retest**: Confirm issue resolved in UAT
6. **Document**: Update documentation if needed

## UAT Sign-Off

UAT is considered complete when:

- [ ] All automated UAT tests pass
- [ ] All manual test scenarios completed successfully
- [ ] All critical and high-severity issues resolved
- [ ] Performance requirements met
- [ ] User feedback collected and documented
- [ ] System ready for production deployment

## Appendix: Sample Data Generation

### Generate Sample Photos Programmatically

```python
from PIL import Image
import os

def generate_sample_photos(output_dir, count=50):
    """Generate sample photos for UAT."""
    os.makedirs(output_dir, exist_ok=True)
    
    for i in range(count):
        # Create varied images
        width = 1920 if i % 3 == 0 else 1280
        height = 1080 if i % 3 == 0 else 960
        color = (i * 5 % 256, (i * 7) % 256, (i * 11) % 256)
        
        img = Image.new('RGB', (width, height), color=color)
        img.save(os.path.join(output_dir, f'photo_{i:03d}.jpg'))

# Generate 50 sample photos
generate_sample_photos('/tmp/uat_photos')
```

## Contact & Support

For UAT issues or questions, contact the development team or refer to [Troubleshooting Guide](TROUBLESHOOTING.md).
