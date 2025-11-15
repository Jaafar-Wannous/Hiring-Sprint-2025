import { Component } from '@angular/core';
import { InspectionComponent } from "./inspection/inspection";

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [InspectionComponent],
  templateUrl: './app.html',
  styleUrl: './app.css'
})
export class App {}
