import { BrowserRouter, Routes, Route } from 'react-router-dom'

import AppLayout from './layouts/AppLayout'
import PatientIntake from './pages/PatientIntake'
import TriageQueue from './pages/TriageQueue'
import PatientDetail from './pages/PatientDetail'
import EditPatient from './pages/EditPatient'


function App() {
    return (
        <BrowserRouter>
            <Routes>
                <Route element={<AppLayout />}>
                    <Route path='/' element={<PatientIntake />} />
                    <Route path='/queue' element={<TriageQueue />} />
                    <Route path='/intakes/:intakeId' element={<PatientDetail />} />
                    <Route path='/intakes/:intakeId/edit' element={<EditPatient />} />
                </Route>
            </Routes>
        </BrowserRouter>
    )
}

export default App
