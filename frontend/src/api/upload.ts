import apiClient from './client';
import type { UploadResponse } from '../types';

export const uploadApi = {
  uploadImages: async (files: FileList): Promise<UploadResponse> => {
    const formData = new FormData();
    Array.from(files).forEach((file) => {
      formData.append('files', file);
    });

    const response = await apiClient.post<UploadResponse>('/api/upload/images', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    });
    return response.data;
  },

  getStatus: async (): Promise<{
    images: { count: number; files: string[] };
  }> => {
    const response = await apiClient.get('/api/upload/status');
    return response.data;
  },
};
