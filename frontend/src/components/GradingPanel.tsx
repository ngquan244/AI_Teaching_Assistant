import React, { useState } from 'react';
import { gradingApi } from '../api/grading';
import { BarChart3, Play, FileSpreadsheet, Loader2, CheckCircle, XCircle } from 'lucide-react';
import PanelHelpButton from './PanelHelpButton';
import type { GradingResponse, GradingResult } from '../types';

const GradingPanel: React.FC = () => {
  const [examCode, setExamCode] = useState('');
  const [executing, setExecuting] = useState(false);
  const [summarizing, setSummarizing] = useState(false);
  const [executeResult, setExecuteResult] = useState<{ success: boolean; message: string } | null>(
    null
  );
  const [gradingResult, setGradingResult] = useState<GradingResponse | null>(null);

  const executeGrading = async () => {
    setExecuting(true);
    setExecuteResult(null);
    try {
      const response = await gradingApi.executeGrading();
      setExecuteResult({
        success: response.success,
        message: response.success
          ? 'Đã chấm điểm thành công!'
          : 'Có lỗi xảy ra khi chấm điểm',
      });
    } catch (error: unknown) {
      const errorMessage = error instanceof Error ? error.message : 'Lỗi khi chấm điểm';
      setExecuteResult({
        success: false,
        message: errorMessage,
      });
    } finally {
      setExecuting(false);
    }
  };

  const summarizeResults = async () => {
    if (!examCode.trim()) {
      alert('Vui lòng nhập mã đề');
      return;
    }

    setSummarizing(true);
    setGradingResult(null);
    try {
      const response = await gradingApi.getSummary({ exam_code: examCode });
      setGradingResult(response);
    } catch (error) {
      console.error('Failed to summarize:', error);
    } finally {
      setSummarizing(false);
    }
  };

  const getScoreColor = (score: number) => {
    if (score >= 8) return 'excellent';
    if (score >= 6.5) return 'good';
    if (score >= 5) return 'average';
    return 'poor';
  };

  return (
    <div className="grading-panel">
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <h2>
          <BarChart3 size={24} />
          Chấm điểm & Tổng hợp kết quả
        </h2>
        <PanelHelpButton panelKey="grading" />
      </div>

      {/* Execute Grading Section */}
      <div className="grading-section">
        <h3>Chấm điểm bài thi</h3>
        <p>Chấm điểm các bài thi đã upload</p>
        <button
          className="btn-primary btn-large"
          onClick={executeGrading}
          disabled={executing}
        >
          {executing ? (
            <>
              <Loader2 className="spin" size={20} />
              Đang chấm điểm...
            </>
          ) : (
            <>
              <Play size={20} />
              Bắt đầu chấm điểm
            </>
          )}
        </button>

        {executeResult && (
          <div className={`result-message ${executeResult.success ? 'success' : 'error'}`}>
            {executeResult.success ? <CheckCircle size={18} /> : <XCircle size={18} />}
            {executeResult.message}
          </div>
        )}
      </div>

      {/* Summary Section */}
      <div className="grading-section">
        <h3>Tổng hợp kết quả theo mã đề</h3>
        <div className="form-row">
          <input
            type="text"
            placeholder="Nhập mã đề (VD: 132)"
            value={examCode}
            onChange={(e) => setExamCode(e.target.value)}
          />
          <button
            className="btn-primary"
            onClick={summarizeResults}
            disabled={summarizing}
          >
            {summarizing ? (
              <Loader2 className="spin" size={18} />
            ) : (
              <FileSpreadsheet size={18} />
            )}
            Tổng hợp
          </button>
        </div>
      </div>

      {/* Results Display */}
      {gradingResult && (
        <div className="grading-results">
          {gradingResult.success ? (
            <>
              <div className="summary-cards">
                <div className="summary-card">
                  <span className="label">Tổng số SV</span>
                  <span className="value">{gradingResult.summary?.total_students}</span>
                </div>
                <div className="summary-card">
                  <span className="label">Điểm TB</span>
                  <span className="value">{gradingResult.summary?.average_score}</span>
                </div>
                <div className="summary-card">
                  <span className="label">Điểm cao nhất</span>
                  <span className="value good">{gradingResult.summary?.max_score}</span>
                </div>
                <div className="summary-card">
                  <span className="label">Điểm thấp nhất</span>
                  <span className="value poor">{gradingResult.summary?.min_score}</span>
                </div>
              </div>

              {gradingResult.overall_assessment && (
                <div className="overall-assessment">
                  <h4>Đánh giá chung:</h4>
                  <p>{gradingResult.overall_assessment}</p>
                </div>
              )}

              <table className="results-table">
                <thead>
                  <tr>
                    <th>MSV</th>
                    <th>Họ tên</th>
                    <th>Email</th>
                    <th>Điểm</th>
                    <th>Đánh giá</th>
                  </tr>
                </thead>
                <tbody>
                  {gradingResult.results.map((result: GradingResult, index: number) => (
                    <tr key={index}>
                      <td>{result.student_id}</td>
                      <td>{result.full_name}</td>
                      <td>{result.email}</td>
                      <td className={getScoreColor(result.score)}>{result.score}</td>
                      <td>{result.evaluation}</td>
                    </tr>
                  ))}
                </tbody>
              </table>

              {gradingResult.excel_file && (
                <div className="export-info">
                  <CheckCircle size={16} />
                  <span>Đã xuất file Excel và gửi email</span>
                </div>
              )}
            </>
          ) : (
            <div className="result-message error">
              <XCircle size={18} />
              {gradingResult.error || 'Không tìm thấy kết quả'}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default GradingPanel;
