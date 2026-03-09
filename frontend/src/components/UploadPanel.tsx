import React, { useState, useCallback } from 'react';
import { uploadApi } from '../api/upload';
import { Upload, ImageIcon, CheckCircle, XCircle, Loader2 } from 'lucide-react';
import PanelHelpButton from './PanelHelpButton';

const UploadPanel: React.FC = () => {
  const [imageFiles, setImageFiles] = useState<File[]>([]);
  const [uploadingImages, setUploadingImages] = useState(false);
  const [imageResult, setImageResult] = useState<{ success: boolean; message: string } | null>(null);

  const handleImageDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    const files = Array.from(e.dataTransfer.files).filter((f) =>
      f.type.startsWith('image/')
    );
    setImageFiles((prev) => [...prev, ...files]);
    setImageResult(null);
  }, []);

  const handleImageSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      const files = Array.from(e.target.files);
      setImageFiles((prev) => [...prev, ...files]);
      setImageResult(null);
    }
  };

  const uploadImages = async () => {
    if (imageFiles.length === 0) return;
    
    setUploadingImages(true);
    try {
      const dt = new DataTransfer();
      imageFiles.forEach((f) => dt.items.add(f));
      const result = await uploadApi.uploadImages(dt.files);
      setImageResult({ success: result.success, message: result.message });
      if (result.success) {
        setImageFiles([]);
      }
    } catch (error) {
      setImageResult({ success: false, message: 'Lỗi khi upload ảnh' });
    } finally {
      setUploadingImages(false);
    }
  };

  const removeImage = (index: number) => {
    setImageFiles((prev) => prev.filter((_, i) => i !== index));
  };

  return (
    <div style={{ maxWidth: 800, color: '#f8fafc' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1.5rem' }}>
        <h2 style={{ fontSize: '1.5rem', margin: 0 }}>Upload Files</h2>
        <PanelHelpButton panelKey="upload" />
      </div>

      <div style={{ background: '#1e293b', border: '1px solid #475569', padding: '1.5rem', borderRadius: 12, marginBottom: '1.5rem' }}>
        <h3 style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '1.1rem', marginBottom: '0.5rem' }}>
          <ImageIcon size={20} />
          Upload ảnh bài thi
        </h3>
        <p style={{ color: '#64748b', fontSize: '0.875rem', marginBottom: '1rem' }}>
          Ảnh sẽ được lưu vào workspace riêng của bạn
        </p>

        <div
          onDrop={handleImageDrop}
          onDragOver={(e) => e.preventDefault()}
          style={{
            border: '2px dashed #6366f1',
            borderRadius: 12,
            padding: '2.5rem 2rem',
            textAlign: 'center',
            cursor: 'pointer',
            position: 'relative',
            background: 'rgba(99, 102, 241, 0.08)',
          }}
        >
          <Upload size={40} style={{ color: '#94a3b8' }} />
          <p style={{ color: '#94a3b8', margin: 0 }}>Kéo thả ảnh vào đây hoặc click để chọn</p>
          <input
            type="file"
            accept="image/*"
            multiple
            onChange={handleImageSelect}
            style={{ position: 'absolute', inset: 0, opacity: 0, cursor: 'pointer' }}
          />
        </div>

        {imageFiles.length > 0 && (
          <div style={{ marginTop: '1rem', paddingTop: '1rem', borderTop: '1px solid #334155' }}>
            <h4 style={{ fontSize: '0.9rem', color: '#94a3b8', marginBottom: '0.75rem' }}>
              Đã chọn {imageFiles.length} ảnh:
            </h4>
            <ul style={{ listStyle: 'none', padding: 0, display: 'flex', flexDirection: 'column', gap: '0.5rem', marginBottom: '1rem' }}>
              {imageFiles.map((file, index) => (
                <li key={index} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0.5rem 0.75rem', background: '#1e293b', borderRadius: '0.5rem' }}>
                  <span>{file.name}</span>
                  <button onClick={() => removeImage(index)} style={{ background: 'none', border: 'none', color: '#ef4444', cursor: 'pointer', fontSize: '1rem' }}>
                    <XCircle size={16} />
                  </button>
                </li>
              ))}
            </ul>
            <button
              onClick={uploadImages}
              disabled={uploadingImages}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '0.5rem',
                padding: '0.75rem 1.5rem',
                background: '#6366f1',
                border: 'none',
                borderRadius: 12,
                color: 'white',
                fontSize: '0.95rem',
                fontWeight: 500,
                cursor: uploadingImages ? 'not-allowed' : 'pointer',
                opacity: uploadingImages ? 0.6 : 1,
              }}
            >
              {uploadingImages ? (
                <><Loader2 className="spin" size={18} /> Đang upload...</>
              ) : (
                <><Upload size={18} /> Upload {imageFiles.length} ảnh</>
              )}
            </button>
          </div>
        )}

        {imageResult && (
          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: '0.5rem',
            padding: '0.875rem 1rem',
            borderRadius: 12,
            marginTop: '1rem',
            background: imageResult.success ? 'rgba(34, 197, 94, 0.15)' : 'rgba(239, 68, 68, 0.15)',
            color: imageResult.success ? '#22c55e' : '#ef4444',
          }}>
            {imageResult.success ? <CheckCircle size={18} /> : <XCircle size={18} />} {imageResult.message}
          </div>
        )}
      </div>
    </div>
  );
};

export default UploadPanel;
