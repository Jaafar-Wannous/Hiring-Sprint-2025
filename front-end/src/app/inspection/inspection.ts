import { CommonModule, TitleCasePipe } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { Component, ElementRef, OnDestroy, ViewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { environment } from '../../environments/environment';

interface RepairDetails {
  damage_type?: string;
  severity?: string;
  area_ratio?: number;
  labor_hours?: number;
  material_units?: number;
  labor_cost?: number;
  material_cost?: number;
  overhead_cost?: number;
  confidence_factor?: number;
  total_cost: number;
}

interface DamageResult {
  label: string;
  severity: string;
  cost: number;
  x: number;
  y: number;
  width: number;
  height: number;
  confidence?: number;
  area_ratio?: number;
  repair_details?: RepairDetails;
}

interface InspectionMetadata {
  pickup_image_count?: number;
  return_image_count?: number;
  total_new_damages?: number;
  total_estimated_cost?: number;
}

interface InspectionDetail {
  id: number;
  pickup_images: Array<{ id: number; path: string; angle?: string | null }>;
  return_images: Array<{ id: number; path: string; angle?: string | null }>;
  damages?: DamageResult[];
  summary?: {
    total_damages: number;
    estimated_cost: number;
  };
}

@Component({
  selector: 'app-inspection',
  standalone: true,
  imports: [CommonModule, TitleCasePipe, FormsModule],
  templateUrl: './inspection.html',
})
export class InspectionComponent implements OnDestroy {
  pickupFiles: File[] = [];
  returnFiles: File[] = [];

  pickupPreviews: string[] = [];
  returnPreviews: string[] = [];

  newDamagesPerImage: DamageResult[][] = [];
  inspectionId?: number;
  pickupSessionId?: number;
  existingInspectionInput = '';
  existingInspectionSummary?: InspectionDetail;
  statusMessage = '';
  statusError = '';
  summary = {
    totalDamages: 0,
    totalCost: 0,
    pickupCount: 0,
    returnCount: 0,
  };
  private readonly apiBase = environment.apiUrl.replace(/\/$/, '');
  private readonly assetBase = environment.apiUrl.replace(/\/api$/, '');

  loading = false;
  dragActive = {
    pickup: false,
    return: false,
  };
  cameraActive = false;
  cameraTarget: 'pickup' | 'return' = 'return';
  cameraError: string | null = null;
  videoStream: MediaStream | null = null;

  @ViewChild('cameraVideo') cameraVideo?: ElementRef<HTMLVideoElement>;
  @ViewChild('cameraCanvas') cameraCanvas?: ElementRef<HTMLCanvasElement>;

  constructor(private http: HttpClient) {}

  ngOnDestroy(): void {
    this.stopCamera();
  }

  onPickupFilesSelected(event: Event): void {
    const element = event.target as HTMLInputElement;
    if (!element.files?.length) return;
    this.applyFiles(element.files, 'pickup');
  }

  async openCamera(group: 'pickup' | 'return'): Promise<void> {
    if (typeof window === 'undefined' || !navigator.mediaDevices?.getUserMedia) {
      alert('Camera access is not supported in this browser.');
      return;
    }

    try {
      this.cameraTarget = group;
      this.cameraActive = true;
      this.cameraError = null;
      this.videoStream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: 'environment' },
        audio: false,
      });
      const videoEl = this.cameraVideo?.nativeElement;
      if (videoEl && this.videoStream) {
        videoEl.srcObject = this.videoStream;
        await videoEl.play();
      }
    } catch (error) {
      console.error('Unable to access camera', error);
      this.cameraError = 'Unable to access the camera. Please allow permissions or try another device.';
      this.cameraActive = false;
      this.stopCamera();
    }
  }

  capturePhoto(): void {
    const videoEl = this.cameraVideo?.nativeElement;
    const canvasEl = this.cameraCanvas?.nativeElement;
    if (!videoEl || !canvasEl) {
      return;
    }

    const width = videoEl.videoWidth || 1280;
    const height = videoEl.videoHeight || 720;
    canvasEl.width = width;
    canvasEl.height = height;
    const ctx = canvasEl.getContext('2d');
    if (!ctx) {
      return;
    }

    ctx.drawImage(videoEl, 0, 0, width, height);
    canvasEl.toBlob(
      (blob) => {
        if (!blob) {
          return;
        }
        const file = new File([blob], `capture-${Date.now()}.jpg`, { type: 'image/jpeg' });
        this.applyFiles([file], this.cameraTarget);
      },
      'image/jpeg',
      0.9,
    );
    this.closeCamera();
  }

  closeCamera(): void {
    this.cameraActive = false;
    this.cameraError = null;
    this.stopCamera();
  }

  private stopCamera(): void {
    this.videoStream?.getTracks().forEach((track) => track.stop());
    this.videoStream = null;
    const videoEl = this.cameraVideo?.nativeElement;
    if (videoEl) {
      videoEl.srcObject = null;
    }
  }

  onReturnFilesSelected(event: Event): void {
    const element = event.target as HTMLInputElement;
    if (!element.files?.length) return;
    this.applyFiles(element.files, 'return');
  }

  onDragOver(event: DragEvent, group: 'pickup' | 'return'): void {
    event.preventDefault();
    event.stopPropagation();
    this.dragActive[group] = true;
  }

  onDragLeave(event: DragEvent, group: 'pickup' | 'return'): void {
    event.preventDefault();
    event.stopPropagation();
    if (event.currentTarget === event.target) {
      this.dragActive[group] = false;
    }
  }

  onDrop(event: DragEvent, group: 'pickup' | 'return'): void {
    event.preventDefault();
    event.stopPropagation();
    this.dragActive[group] = false;
    const files = event.dataTransfer?.files;
    if (files?.length) {
      this.applyFiles(files, group);
      event.dataTransfer?.clearData();
    }
  }

  submitInspection(): void {
    if (this.returnFiles.length === 0) {
      alert('Please add return photos to analyze the car.');
      return;
    }

    const canReuseBaseline = !!this.pickupSessionId && this.pickupFiles.length === 0;
    if (canReuseBaseline) {
      this.submitReturnForExisting();
    } else {
      this.submitCombinedInspection();
    }
  }

  savePickupBaseline(): void {
    if (this.pickupFiles.length === 0) {
      alert('Add at least one pick-up photo before saving the baseline.');
      return;
    }
    this.loading = true;
    this.clearStatus();

    const formData = new FormData();
    for (const file of this.pickupFiles) {
      formData.append('pickup_images[]', file, file.name);
    }

    this.http.post(this.buildApiUrl('/inspections/pickup'), formData).subscribe({
      next: (response: any) => {
        this.pickupSessionId = response.inspection_id;
        this.inspectionId = response.inspection_id;
        this.statusMessage = `Pickup session saved (Inspection #${response.inspection_id}). Share this id to resume later.`;
        this.existingInspectionInput = String(response.inspection_id);
        this.existingInspectionSummary = undefined;
        this.pickupFiles = [];
        this.pickupPreviews = [];
        this.loading = false;
      },
      error: (error) => {
        this.handleRequestError('Unable to save the pickup baseline. Please try again.', error);
      },
    });
  }

  resumeInspection(): void {
    const normalized = this.existingInspectionInput.trim();
    const parsedId = Number(normalized);
    if (!Number.isInteger(parsedId) || parsedId <= 0) {
      alert('Enter a valid inspection id to resume.');
      return;
    }
    this.loading = true;
    this.clearStatus();
    this.pickupSessionId = undefined;
    this.existingInspectionSummary = undefined;
    this.resetResults();
    this.pickupFiles = [];
    this.pickupPreviews = [];
    this.returnFiles = [];
    this.returnPreviews = [];

    this.http.get<InspectionDetail>(this.buildApiUrl(`/inspections/${parsedId}`)).subscribe({
      next: (detail) => {
        this.pickupSessionId = detail.id;
        this.inspectionId = detail.id;
        this.existingInspectionSummary = detail;
        this.pickupPreviews = detail.pickup_images.map((img) => this.resolveImageUrl(img.path));
        this.returnPreviews = detail.return_images.map((img) => this.resolveImageUrl(img.path));
        this.newDamagesPerImage = this.groupDamagesByReturnImage(detail);
        this.updateSummary({
          total_new_damages: detail.summary?.total_damages,
          total_estimated_cost: detail.summary?.estimated_cost,
          pickup_image_count: detail.pickup_images.length,
          return_image_count: detail.return_images.length,
        });
        this.statusMessage = `Inspection #${detail.id} loaded. Upload return photos and run the analysis.`;
        this.loading = false;
      },
      error: (error) => {
        this.existingInspectionSummary = undefined;
        this.pickupSessionId = undefined;
        this.handleRequestError('Inspection not found. Double-check the id and try again.', error);
      },
    });
  }

  private submitCombinedInspection(): void {
    this.loading = true;
    this.resetResults();
    this.clearStatus();

    const formData = new FormData();
    for (const file of this.pickupFiles) {
      formData.append('pickup_images[]', file, file.name);
    }
    for (const file of this.returnFiles) {
      formData.append('return_images[]', file, file.name);
    }

    this.http.post(this.buildApiUrl('/inspections'), formData).subscribe({
      next: (response: any) => {
        this.pickupFiles = [];
        this.pickupPreviews = [];
        this.handleAnalysisResponse(response);
      },
      error: (error) => this.handleRequestError('Image analysis failed. Please try again later.', error),
    });
  }

  private submitReturnForExisting(): void {
    if (!this.pickupSessionId) {
      return;
    }

    this.loading = true;
    this.resetResults();
    this.clearStatus();

    const formData = new FormData();
    for (const file of this.returnFiles) {
      formData.append('return_images[]', file, file.name);
    }

    this.http.post(this.buildApiUrl(`/inspections/${this.pickupSessionId}/return`), formData).subscribe({
      next: (response: any) => this.handleAnalysisResponse(response),
      error: (error) =>
        this.handleRequestError('Unable to compare against the saved baseline. Please try again.', error),
    });
  }

  private applyFiles(collection: FileList | File[], group: 'pickup' | 'return'): void {
    const normalized = Array.from(collection as ArrayLike<File>);
    if (!normalized.length) {
      return;
    }

    if (group === 'pickup') {
      this.clearPickupSessionContext();
      this.clearStatus();
      const updatedFiles = [...this.pickupFiles, ...normalized];
      const updatedPreviews = [...this.pickupPreviews];
      normalized.forEach((file) =>
        this.readFilePreview(file, (dataUrl) => {
          updatedPreviews.push(dataUrl);
          this.pickupPreviews = [...updatedPreviews];
        }),
      );
      this.pickupFiles = updatedFiles;
      this.pickupPreviews = [...updatedPreviews];
    } else {
      this.clearStatus();
      const updatedFiles = [...this.returnFiles, ...normalized];
      const updatedPreviews = [...this.returnPreviews];
      normalized.forEach((file) =>
        this.readFilePreview(file, (dataUrl) => {
          updatedPreviews.push(dataUrl);
          this.returnPreviews = [...updatedPreviews];
        }),
      );
      this.returnFiles = updatedFiles;
      this.returnPreviews = [...updatedPreviews];
    }
  }

  formatCurrency(value: number): string {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      maximumFractionDigits: 0,
    }).format(value || 0);
  }

  formatPercent(value?: number): string {
    if (value === undefined || value === null) {
      return 'N/A';
    }
    return `${Math.round(value * 100)}%`;
  }

  formatHours(value?: number): string {
    if (value === undefined || value === null) {
      return '--';
    }
    return `${value.toFixed(1)}h`;
  }

  formatNumber(value?: number, fractionDigits = 0): string {
    if (value === undefined || value === null) {
      return '--';
    }
    return value.toFixed(fractionDigits);
  }
  private readFilePreview(file: File, onLoad: (dataUrl: string) => void): void {
    const reader = new FileReader();
    reader.onload = (e: ProgressEvent<FileReader>) => {
      if (e.target?.result) {
        onLoad(e.target.result as string);
      }
    };
    reader.readAsDataURL(file);
  }

  private handleAnalysisResponse(response: any): void {
    this.inspectionId = response?.inspection_id;
    if (this.inspectionId) {
      this.pickupSessionId = this.inspectionId;
    }
    this.newDamagesPerImage = response?.results ?? [];
    this.updateSummary(response?.metadata);
    this.loading = false;
    this.statusError = '';
    this.statusMessage = this.inspectionId
      ? `Inspection #${this.inspectionId} analyzed successfully.`
      : 'Analysis completed.';
  }

  private handleRequestError(message: string, error: unknown): void {
    console.error(message, error);
    this.statusError = message;
    this.loading = false;
  }

  private resetResults(): void {
    this.newDamagesPerImage = [];
    this.summary = { totalDamages: 0, totalCost: 0, pickupCount: 0, returnCount: 0 };
    this.inspectionId = undefined;
  }

  private clearStatus(): void {
    this.statusMessage = '';
    this.statusError = '';
  }

  private clearPickupSessionContext(): void {
    this.pickupSessionId = undefined;
    this.existingInspectionSummary = undefined;
    this.inspectionId = undefined;
  }

  private buildApiUrl(path: string): string {
    const normalized = path.startsWith('/') ? path : `/${path}`;
    return `${this.apiBase}${normalized}`;
  }

  private updateSummary(metadata?: InspectionMetadata): void {
    let computedDamages = 0;
    let computedCost = 0;

    for (const damages of this.newDamagesPerImage) {
      for (const damage of damages) {
        computedDamages += 1;
        computedCost += damage.cost;
      }
    }

    this.summary = {
      totalDamages: metadata?.total_new_damages ?? computedDamages,
      totalCost: metadata?.total_estimated_cost ?? computedCost,
      pickupCount: metadata?.pickup_image_count ?? this.pickupPreviews.length,
      returnCount: metadata?.return_image_count ?? this.returnPreviews.length,
    };
  }

  private resolveImageUrl(path: string): string {
    if (!path) return '';
    if (/^https?:\/\//i.test(path)) {
      return path;
    }
    const normalized = path.replace(/^\/+/, '');
    return `${this.assetBase}/${normalized}`;
  }

  private groupDamagesByReturnImage(detail: InspectionDetail): DamageResult[][] {
    if (!detail.return_images.length) {
      return [];
    }
    const indexById = new Map<number, number>();
    detail.return_images.forEach((img, idx) => indexById.set(img.id, idx));
    const grouped: DamageResult[][] = detail.return_images.map(() => []);
    for (const damage of detail.damages ?? []) {
      const targetIdx = indexById.get((damage as any).image_id);
      if (targetIdx === undefined) continue;
      grouped[targetIdx].push({
        label: (damage as any).label ?? (damage as any).type ?? 'Damage',
        severity: (damage as any).severity ?? 'unknown',
        cost: (damage as any).estimated_cost ?? (damage as any).cost ?? 0,
        x: (damage as any).x ?? 0,
        y: (damage as any).y ?? 0,
        width: (damage as any).width ?? 0,
        height: (damage as any).height ?? 0,
        confidence: (damage as any).confidence,
        area_ratio: (damage as any).area_ratio,
        repair_details: (damage as any).repair_details,
      });
    }
    return grouped;
  }
}

