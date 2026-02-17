import { useCallback, useState } from 'react';
import { useDropzone } from 'react-dropzone';
import { Upload, File, X, ScanLine } from 'lucide-react';
import { cn } from '../lib/utils';
import { Button } from './ui/button';

interface FileUploaderProps {
  /** Called immediately when a file is dropped/chosen — for staging only. */
  onFileSelect: (file: File) => void;
  accept?: Record<string, string[]>;
  label?: string;
  className?: string;
  isLoading?: boolean;
  /** If provided, the component is controlled: shows this file instead of internal state. */
  stagedFile?: File | null;
  /** Called when the user clicks the ✕ to clear the staged file. */
  onClear?: () => void;
  /** If provided, a Scan button is shown inside the dropzone when a file is staged. */
  onScan?: () => void;
  /** Label for the scan button */
  scanLabel?: string;
}

export function FileUploader({
  onFileSelect,
  accept = {
    'image/*': ['.jpg', '.jpeg', '.png', '.webp'],
    'application/pdf': ['.pdf'],
  },
  label = 'Drop receipt or invoice here',
  className,
  isLoading,
  stagedFile,
  onClear,
  onScan,
  scanLabel = 'Scan Document',
}: FileUploaderProps) {
  const [internalFile, setInternalFile] = useState<File | null>(null);
  // Use controlled file if provided, otherwise internal
  const selectedFile = stagedFile !== undefined ? stagedFile : internalFile;

  const onDrop = useCallback(
    (files: File[]) => {
      if (files[0]) {
        if (stagedFile === undefined) setInternalFile(files[0]);
        onFileSelect(files[0]);
      }
    },
    [onFileSelect, stagedFile]
  );

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept,
    maxFiles: 1,
    disabled: isLoading,
  });

  const clear = (e: React.MouseEvent) => {
    e.stopPropagation();
    setInternalFile(null);
    onClear?.();
  };

  const scan = (e: React.MouseEvent) => {
    e.stopPropagation();
    onScan?.();
  };

  return (
    <div
      {...getRootProps()}
      className={cn(
        'relative flex flex-col items-center justify-center rounded-lg border-2 border-dashed p-8 transition-colors cursor-pointer',
        isDragActive ? 'border-primary bg-primary/5' : 'border-muted-foreground/25 hover:border-primary/50',
        isLoading && 'opacity-50 cursor-not-allowed',
        selectedFile && !isLoading && 'border-primary/40 bg-primary/5',
        className
      )}
    >
      <input {...getInputProps()} />
      {selectedFile ? (
        <div className="flex flex-col items-center gap-4 w-full">
          {/* File info row */}
          <div className="flex items-center gap-3">
            <File className="h-8 w-8 text-primary shrink-0" />
            <div className="text-left">
              <p className="text-sm font-medium">{selectedFile.name}</p>
              <p className="text-xs text-muted-foreground">
                {(selectedFile.size / 1024).toFixed(1)} KB — ready to scan
              </p>
            </div>
            <Button variant="ghost" size="icon" onClick={clear} className="ml-2 shrink-0" title="Remove file">
              <X className="h-4 w-4" />
            </Button>
          </div>

          {/* Scan button (only when onScan is provided) */}
          {onScan && (
            <Button onClick={scan} className="gap-2 w-full max-w-xs" size="lg">
              <ScanLine className="h-4 w-4" />
              {scanLabel}
            </Button>
          )}
        </div>
      ) : (
        <>
          <Upload className="h-10 w-10 text-muted-foreground mb-3" />
          <p className="text-sm font-medium">{label}</p>
          <p className="text-xs text-muted-foreground mt-1">
            {isDragActive ? 'Release to upload' : 'or click to browse'}
          </p>
        </>
      )}
      {isLoading && (
        <div className="absolute inset-0 flex items-center justify-center rounded-lg bg-background/80">
          <div className="text-sm text-muted-foreground animate-pulse">Processing with AI...</div>
        </div>
      )}
    </div>
  );
}
