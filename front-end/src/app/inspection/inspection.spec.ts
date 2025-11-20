import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient, withInterceptorsFromDi } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { InspectionComponent } from './inspection';
import { environment } from '../../environments/environment';

describe('InspectionComponent', () => {
  let component: InspectionComponent;
  let fixture: ComponentFixture<InspectionComponent>;
  let httpMock: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [InspectionComponent],
      providers: [
        provideHttpClient(withInterceptorsFromDi()),
        provideHttpClientTesting(),
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(InspectionComponent);
    component = fixture.componentInstance;
    httpMock = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('clears local files and previous results when resuming an inspection', () => {
    component.returnFiles = [new File([''], 'return.jpg')];
    component.returnPreviews = ['data:return'];
    component.pickupFiles = [new File([''], 'pickup.jpg')];
    component.pickupPreviews = ['data:pickup'];
    component.newDamagesPerImage = [[{ label: 'scratch', severity: 'minor', cost: 50, x: 0, y: 0, width: 0.1, height: 0.1 }]];
    component.summary = { totalDamages: 1, totalCost: 50, pickupCount: 1, returnCount: 1 };
    component.existingInspectionInput = '42';

    component.resumeInspection();

    expect(component.returnFiles.length).toBe(0);
    expect(component.returnPreviews.length).toBe(0);
    expect(component.pickupFiles.length).toBe(0);
    expect(component.pickupPreviews.length).toBe(0);
    expect(component.newDamagesPerImage.length).toBe(0);
    expect(component.summary).toEqual({ totalDamages: 0, totalCost: 0, pickupCount: 0, returnCount: 0 });

    const req = httpMock.expectOne(`${environment.apiUrl}/inspections/42`);
    expect(req.request.method).toBe('GET');

    req.flush({ id: 42, pickup_images: [], return_images: [] });

    expect(component.pickupSessionId).toBe(42);
    expect(component.inspectionId).toBe(42);
    expect(component.existingInspectionSummary?.id).toBe(42);
  });
});
