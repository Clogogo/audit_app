import { useCallback, useState } from 'react';
import { useDropzone } from 'react-dropzone';
import { Upload, File, X } from 'lucide-react';
import { cn } from '../lib/utils';
import { Button } from './ui/button';

interface FileUploaderProps {
  onFileSelect: (file: File) => void;
  accept?: Record<string, string[]>;
  label?: string;
  className?: string;
  isLoading?: boolean;
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
}: FileUploaderProps) {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);

  const onDrop = useCallback(
    (files: File[]) => {
      if (files[0]) {
        setSelectedFile(files[0]);
        onFileSelect(files[0]);
      }
    },
    [onFileSelect]
  );

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept,
    maxFiles: 1,
    disabled: isLoading,
  });

  const clear = (e: React.MouseEvent) => {
    e.stopPropagation();
    setSelectedFile(null);
  };

  return (
    <div
      {...getRootProps()}
      className={cn(
        'relative flex flex-col items-center justify-center rounded-lg border-2 border-dashed p-8 transition-colors cursor-pointer',
        isDragActive ? 'border-primary bg-primary/5' : 'border-muted-foreground/25 hover:border-primary/50',
        isLoading && 'opacity-50 cursor-not-allowed',
        className
      )}
    >
      <input {...getInputProps()} />
      {selectedFile ? (
        <div className="flex items-center gap-3">
          <File className="h-8 w-8 text-primary" />
          <div>
            <p className="text-sm font-medium">{selectedFile.name}</p>
            <p className="text-xs text-muted-foreground">
              {(selectedFile.size / 1024).toFixed(1)} KB
            </p>
          </div>
          <Button variant="ghost" size="icon" onClick={clear} className="ml-2">
            <X className="h-4 w-4" />
          </Button>
        </div>
      ) : (
        <>
          <Upload className="h-10 w-10 text-muted-foreground mb-3" />
          <p className="text-sm font-medium">{label}</p>
          <p className="text-xs text-muted-foreground mt-1">
            {isDragActive ? 'Release to upload' : 'or click to browse — JPG, PNG, PDF'}
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
