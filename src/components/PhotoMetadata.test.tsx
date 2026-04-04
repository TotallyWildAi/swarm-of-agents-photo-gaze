import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import PhotoMetadata from './PhotoMetadata';
import { Photo } from '../api';

describe('PhotoMetadata Component', () => {
  const mockPhoto: Photo = {
    photo_id: 1,
    filename: 'test_photo.jpg',
    path: '/photos/test_photo.jpg',
    quality_score: 0.95,
    similarity_score: 0.92,
    dimensions: '1920x1080',
    file_size: 2048576,
    is_original: true,
    is_duplicate: false,
  };

  test('renders filename', () => {
    render(<PhotoMetadata photo={mockPhoto} />);
    expect(screen.getByText('test_photo.jpg')).toBeInTheDocument();
  });

  test('displays original status badge when is_original is true', () => {
    render(<PhotoMetadata photo={mockPhoto} />);
    expect(screen.getByText('Original')).toBeInTheDocument();
  });

  test('displays duplicate status badge when is_duplicate is true', () => {
    const duplicatePhoto: Photo = { ...mockPhoto, is_original: false, is_duplicate: true };
    render(<PhotoMetadata photo={duplicatePhoto} />);
    expect(screen.getByText('Duplicate')).toBeInTheDocument();
  });

  test('displays quality score with label', () => {
    render(<PhotoMetadata photo={mockPhoto} />);
    expect(screen.getByText('Quality:')).toBeInTheDocument();
    expect(screen.getByText('Excellent (95.0%)')).toBeInTheDocument();
  });

  test('displays dimensions when provided', () => {
    render(<PhotoMetadata photo={mockPhoto} />);
    expect(screen.getByText('Dimensions:')).toBeInTheDocument();
    expect(screen.getByText('1920x1080')).toBeInTheDocument();
  });

  test('displays file size when provided', () => {
    render(<PhotoMetadata photo={mockPhoto} />);
    expect(screen.getByText('Size:')).toBeInTheDocument();
    expect(screen.getByText('2.0 MB')).toBeInTheDocument();
  });

  test('displays 5-6 key metadata fields in summary', () => {
    render(<PhotoMetadata photo={mockPhoto} />);
    const metadataItems = screen.getAllByRole('img', { hidden: true }).length;
    // Check for presence of key fields
    expect(screen.getByText('Quality:')).toBeInTheDocument();
    expect(screen.getByText('Dimensions:')).toBeInTheDocument();
    expect(screen.getByText('Size:')).toBeInTheDocument();
    expect(screen.getByText('Original')).toBeInTheDocument();
  });

  test('expands details when expand button clicked', async () => {
    const user = userEvent.setup();
    render(<PhotoMetadata photo={mockPhoto} />);
    const expandButton = screen.getByRole('button');
    await user.click(expandButton);
    expect(screen.getByText('Photo ID:')).toBeInTheDocument();
    expect(screen.getByText('1')).toBeInTheDocument();
  });

  test('displays path in expandable details', async () => {
    const user = userEvent.setup();
    render(<PhotoMetadata photo={mockPhoto} />);
    const expandButton = screen.getByRole('button');
    await user.click(expandButton);
    expect(screen.getByText('Path:')).toBeInTheDocument();
    expect(screen.getByText('/photos/test_photo.jpg')).toBeInTheDocument();
  });

  test('displays similarity score in expandable details', async () => {
    const user = userEvent.setup();
    render(<PhotoMetadata photo={mockPhoto} />);
    const expandButton = screen.getByRole('button');
    await user.click(expandButton);
    expect(screen.getByText('Similarity Score:')).toBeInTheDocument();
    expect(screen.getByText('92.0%')).toBeInTheDocument();
  });

  test('collapses details when expand button clicked again', async () => {
    const user = userEvent.setup();
    render(<PhotoMetadata photo={mockPhoto} />);
    const expandButton = screen.getByRole('button');
    await user.click(expandButton);
    expect(screen.getByText('Photo ID:')).toBeInTheDocument();
    await user.click(expandButton);
    expect(screen.queryByText('Photo ID:')).not.toBeInTheDocument();
  });

  test('applies reference class when isReference is true', () => {
    const { container } = render(<PhotoMetadata photo={mockPhoto} isReference={true} />);
    const metadataDiv = container.querySelector('.photo-metadata.reference');
    expect(metadataDiv).toBeInTheDocument();
  });

  test('formats file size correctly for different sizes', () => {
    const smallPhoto: Photo = { ...mockPhoto, file_size: 512 };
    const { rerender } = render(<PhotoMetadata photo={smallPhoto} />);
    expect(screen.getByText('512 B')).toBeInTheDocument();

    const largePhoto: Photo = { ...mockPhoto, file_size: 1024 * 1024 * 5 };
    rerender(<PhotoMetadata photo={largePhoto} />);
    expect(screen.getByText('5.0 MB')).toBeInTheDocument();
  });

  test('displays quality labels correctly for different scores', () => {
    const goodPhoto: Photo = { ...mockPhoto, quality_score: 0.85 };
    const { rerender } = render(<PhotoMetadata photo={goodPhoto} />);
    expect(screen.getByText('Good (85.0%)')).toBeInTheDocument();

    const fairPhoto: Photo = { ...mockPhoto, quality_score: 0.75 };
    rerender(<PhotoMetadata photo={fairPhoto} />);
    expect(screen.getByText('Fair (75.0%)')).toBeInTheDocument();
  });

  test('handles missing optional fields gracefully', () => {
    const minimalPhoto: Photo = {
      photo_id: 2,
      filename: 'minimal.jpg',
      path: '/photos/minimal.jpg',
      quality_score: 0.8,
    };
    render(<PhotoMetadata photo={minimalPhoto} />);
    expect(screen.getByText('minimal.jpg')).toBeInTheDocument();
    expect(screen.getByText('Good (80.0%)')).toBeInTheDocument();
    expect(screen.queryByText('Dimensions:')).not.toBeInTheDocument();
  });
});
